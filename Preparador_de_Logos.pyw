"""EmbImage: preparação de logos e interface guiada para bordado.
Não gera arquivos de pontos nem PES.
"""
from __future__ import annotations
import argparse
from io import BytesIO
import sys
import tkinter as tk
import cv2
import numpy as np
from PIL import Image, ImageOps

from embimage_ui import EmbImageApp

BACKGROUNDS = ['Não remover', 'Automático (cor do canto)', 'Escolher com clique']
EXPORT_BACKGROUNDS = ['Branco (recomendado para PE-Design)', 'Transparente', 'Preto', 'Cor personalizada']
PALETTE_SIZE = 8
BACKGROUND_TOLERANCE = 45
OUTPUT_MAX_SIDE = 2000
# A tolerância é aplicada em pixels da saída de 2000 px, nunca na entrada pequena.
EDGE_SMOOTHNESS = {1: 0.3, 2: 0.6, 3: 1.0}


def load_image(path):
    with Image.open(path) as im:
        source_format=im.format
        im = ImageOps.exif_transpose(im).convert('RGBA')
        if max(im.size) > 4200: im.thumbnail((4200, 4200), Image.Resampling.LANCZOS)
        result=im.copy()
        result.info['embimage_source_format']=source_format
        return result


def color_at_corner(img):
    a=np.asarray(img.convert('RGBA'))[:,:,:3]
    h,w=a.shape[:2]
    z=max(1,min(h,w)//22)
    corners=np.concatenate([a[:z,:z].reshape(-1,3),a[:z,-z:].reshape(-1,3),a[-z:,:z].reshape(-1,3),a[-z:,-z:].reshape(-1,3)])
    return tuple(int(i) for i in np.median(corners,axis=0))


def color_key_mask(rgb, chosen, tolerance):
    """Distância adaptativa em HSV para fundos cromáticos; em LAB para fundos neutros.
    Retorna a máscara de pixels semelhantes à cor amostrada, inclusive variações de iluminação.
    """
    col = np.uint8([[chosen]])
    hsv_c = cv2.cvtColor(col, cv2.COLOR_RGB2HSV)[0,0]
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    t=float(tolerance)
    if hsv_c[1] >= 58 and hsv_c[2] >= 38:
        # Para uma cor viva, permitir variações de luminosidade mais amplas,
        # mas proteger pixels pretos/cinza com baixa saturação.
        dh=np.abs(hsv[:,:,0].astype('int16')-int(hsv_c[0]))
        dh=np.minimum(dh, 180-dh)
        hue_allow=3.5 + t * 0.20
        sat_floor=max(42, float(hsv_c[1]) * (0.85-t/150.0))
        # Sombras e blocos de JPEG podem manter a mesma cor do fundo com
        # luminosidade muito menor. Saturação e matiz continuam protegendo
        # as tintas neutras; não deixe esses resíduos virarem pontos pretos.
        val_floor=8
        return (dh<=hue_allow)&(hsv[:,:,1]>=sat_floor)&(hsv[:,:,2]>=val_floor)
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB).astype(np.float32)
    sample_lab=cv2.cvtColor(col,cv2.COLOR_RGB2LAB)[0,0].astype(np.float32)
    diff=np.sqrt(np.sum((lab-sample_lab)**2,axis=2))
    return diff <= 7.0+t*0.85


def connected_to_border(mask):
    mask=np.uint8(mask)
    n, labels = cv2.connectedComponents(mask, connectivity=8)
    if n<=1: return np.zeros_like(mask,dtype=bool)
    border=np.unique(np.r_[labels[0,:],labels[-1,:],labels[:,0],labels[:,-1]])
    return np.isin(labels,border[border>0])


def remove_background(rgba, color, tolerance, anywhere=True):
    a=rgba.copy()
    mask=color_key_mask(a[:,:,:3],color,tolerance)&(a[:,:,3]>0)
    if not anywhere: mask=connected_to_border(mask)
    # Suavização mínima das bordas, mantendo áreas transparentes e nitidez.
    old_alpha=a[:,:,3].astype(np.float32)
    mask_8=np.uint8(mask)*255
    # Um pouco de suavização nas bordas sem criar linhas pesadas.
    blurred=cv2.GaussianBlur(mask_8,(3,3),0.65).astype(np.float32)/255.0
    a[:,:,3]=np.uint8(np.clip(old_alpha*(1.0-blurred),0,255))
    a[mask,3]=0
    return a


def refine_neutral_jpeg_matte(rgba, background):
    """Separa tinta neutra de um fundo cromático sem seguir blocos do JPEG."""
    bg=np.asarray(background,dtype=np.float32)
    if np.ptp(bg)<60:
        return rgba
    rgb=rgba[:,:,:3]
    strong=rgba[:,:,3]>192
    samples=rgb[strong]
    if len(samples)<32:
        return rgba
    samples=samples[::max(1,len(samples)//40000)]
    if np.mean(np.ptp(samples.astype(np.int16),axis=1)<25)<.97:
        return rgba
    # A cromaticidade da tinta preta/cinza é zero. Sua luminosidade pode
    # variar livremente, inclusive nos brilhos cinza, sem criar furos na arte.
    direction=bg-np.mean(bg)
    background_fraction=np.sum(rgb.astype(np.float32)*direction,axis=2)/np.dot(direction,direction)
    coverage=np.clip(1-background_fraction,0,1)
    # Um pontinho preto comprimido pode ficar avermelhado e escapar da
    # máscara por matiz. Recupere pequenos sinais coerentes de tinta, sem
    # promover um único pixel de compressão a um novo componente da arte.
    candidates=np.uint8((coverage>.5)&~connected_to_border(coverage>.5))
    count,labels,stats,_=cv2.connectedComponentsWithStats(candidates,connectivity=8)
    accepted=np.zeros(count,dtype=bool)
    accepted[1:]=stats[1:,cv2.CC_STAT_AREA]>=3
    near=cv2.dilate(np.uint8(strong|accepted[labels]),np.ones((7,7),np.uint8)).astype(bool)
    out=rgba.copy()
    out[:,:,3]=np.uint8(coverage*255)
    out[~near,3]=0
    # Regiões internas da cor do fundo já protegidas continuam protegidas.
    protected=strong&color_key_mask(rgb,background,BACKGROUND_TOLERANCE)
    out[protected,3]=rgba[protected,3]
    return out


def detect_palette(rgba, max_colors=PALETTE_SIZE):
    """Encontra as cores predominantes visíveis, ordenadas por ocorrência."""
    rgb=rgba[:,:,:3]
    good=rgba[:,:,3]>32
    pts=rgb[good]
    if pts.size==0: return []
    sample=pts[::max(1,len(pts)//40000)]
    lab=cv2.cvtColor(sample.reshape(1,-1,3),cv2.COLOR_RGB2LAB).reshape(-1,3).astype(np.float32)
    k=min(max_colors,len(lab))
    cv2.setRNGSeed(7)
    _, labels, centers=cv2.kmeans(lab,k,None,(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,20,0.6),3,cv2.KMEANS_PP_CENTERS)
    palette=cv2.cvtColor(np.uint8(np.clip(centers,0,255)).reshape(1,-1,3),cv2.COLOR_LAB2RGB).reshape(-1,3)
    counts=np.bincount(labels.ravel(),minlength=k)
    order=np.argsort(-counts)
    return [tuple(int(value) for value in palette[index]) for index in order]


def apply_palette(rgba, palette, replacements):
    """Agrupa pixels na paleta detectada e aplica as substituições escolhidas."""
    if not palette:
        return rgba
    rgb=rgba[:,:,:3]
    centers_rgb=np.asarray(palette,dtype=np.uint8)
    centers=cv2.cvtColor(centers_rgb.reshape(1,-1,3),cv2.COLOR_RGB2LAB).reshape(-1,3).astype(np.float32)
    flat=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB).reshape(-1,3).astype(np.float32)
    chosen=np.empty((len(flat),),dtype=np.int16)
    for i in range(0,len(flat),150000):
        p=flat[i:i+150000]
        chosen[i:i+len(p)]=np.argmin(((p[:,None,:]-centers[None,:,:])**2).sum(axis=2),axis=1)
    targets=np.asarray([replacements.get(color,color) for color in palette],dtype=np.uint8)
    out=rgba.copy()
    out[:,:,:3]=targets[chosen].reshape(rgb.shape)
    return out


def vectorize_to_png(rgba, palette, replacements, smoothness, preserve_details=False, curve_scale=1.):
    """Traça a imagem já reduzida à paleta e a renderiza novamente em até 2000 px.

    O SVG existe apenas em memória: a saída pública do app continua sendo PNG.
    """
    try:
        import resvg_py
        import vtracer
    except ImportError as exc:
        raise RuntimeError('Instale as dependências do projeto com: python -m pip install -r requirements.txt') from exc
    source=Image.fromarray(rgba,'RGBA')
    if not palette:
        factor=OUTPUT_MAX_SIDE/max(source.size)
        return source.resize((max(1,round(source.width*factor)),max(1,round(source.height*factor))),Image.Resampling.LANCZOS)
    source_bytes=BytesIO()
    source.save(source_bytes,format='PNG')
    target_colors=[]
    for color in palette:
        target=replacements.get(color,color)
        if target not in target_colors:
            target_colors.append(target)
    config=vtracer.Config(mode='spline',hierarchical='cutout',filter_speckle=0,
                          color_precision=8,layer_difference=0,path_precision=3)
    config.palette=['#%02x%02x%02x' % color for color in target_colors]
    # Com detalhes finos, uma simplificação comum pode eliminar curvas e
    # segmentos de apenas poucos pixels. O valor bem baixo mantém esses
    # segmentos, mas ainda deixa a borda vetorial mais limpa que um raster
    # ampliado diretamente.
    config.simplify=0.08 if preserve_details else EDGE_SMOOTHNESS[smoothness]*curve_scale
    svg=config.convert_bytes(source_bytes.getvalue())
    factor=OUTPUT_MAX_SIDE/max(source.size)
    width=max(1,round(source.width*factor))
    height=max(1,round(source.height*factor))
    svg_string=svg.decode('utf-8') if isinstance(svg,bytes) else svg
    png=resvg_py.svg_to_bytes(svg_string=svg_string,width=width,height=height)
    with Image.open(BytesIO(png)) as result:
        return result.convert('RGBA').copy()


def restore_delicate_regions(source, prepared_alpha, traced, palette, replacements, background, remove_bg, detail_radius=6):
    """Preserva a cobertura original onde uma curva muito fina ficou deformada.

    Um traço com menos de um pixel não pode ser transformado em um bloco opaco:
    sua cobertura parcial é o que define a espessura aparente. A recuperação
    atua só em componentes estreitos e respeita as trocas explícitas de cores.
    """
    if not palette:
        return traced
    raw=np.asarray(source.convert('RGBA'))
    rgb=raw[:,:,:3].astype(np.float32)
    bg=np.asarray(background,dtype=np.float32)
    colors=np.asarray(palette,dtype=np.float32)
    contrast=np.sum((colors-bg)**2,axis=1)
    anchors=np.flatnonzero(contrast>32**2)
    if not len(anchors):
        return traced
    anchors=anchors[np.argsort(-contrast[anchors])]
    targets=np.asarray([replacements.get(tuple(map(int,color)),tuple(map(int,color))) for color in colors],dtype=np.float32)
    background_target=targets[int(np.argmin(contrast))]
    visible=(np.max(np.abs(rgb-bg),axis=2)>18)&(raw[:,:,3]>16)
    if remove_bg and np.ptp(bg)>45:
        # Variações do fundo colorido e blocos JPEG não são detalhes da arte.
        # Respeite a máscara já calculada antes de tentar recuperar seus fios.
        visible&=prepared_alpha>=128
    count,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(visible),connectivity=8)
    radii=cv2.distanceTransform(np.uint8(visible),cv2.DIST_L2,5)
    output=np.asarray(traced).copy()
    shown=output[:,:,:3].astype(np.float32)*(output[:,:,3:4]/255.0)+bg*(1-output[:,:,3:4]/255.0)
    output_visible=np.max(np.abs(shown-bg),axis=2)>18
    for label in range(1,count):
        x,y,width,height,area=stats[label]
        if area<4:
            continue
        local=labels[y:y+height,x:x+width]==label
        local_radii=radii[y:y+height,x:x+width][local]
        if np.max(local_radii)>detail_radius:
            # Uma cruz ou uma junção é mais larga que suas hastes. Em redes
            # longas de linhas, examine a espessura predominante, sem tratar
            # letras pequenas e regiões sólidas como se fossem fios.
            if max(width,height)<detail_radius*20 or np.quantile(local_radii,.9)>detail_radius:
                continue
        x0,y0=max(0,x-3),max(0,y-3)
        x1,y1=min(raw.shape[1],x+width+3),min(raw.shape[0],y+height+3)
        component=labels[y0:y1,x0:x1]==label
        region=cv2.dilate(np.uint8(component),np.ones((5,5),np.uint8)).astype(bool)
        actual=output_visible[y0:y1,x0:x1]&region
        overlap=np.count_nonzero(component&actual)/max(1,np.count_nonzero(component|actual))
        if overlap>.86 and not replacements:
            continue
        patch=rgb[y0:y1,x0:x1]
        core=patch[component]
        strength=np.sum((core-bg)**2,axis=1)
        core=core[strength>=np.max(strength)*.9]
        core=core[::max(1,len(core)//2000)]
        group_scores={}
        for anchor in anchors:
            target=tuple(targets[anchor])
            distance=float(np.min(np.sum((core-colors[anchor])**2,axis=1)))
            group_scores[target]=min(group_scores.get(target,float('inf')),distance)
        ordered=sorted(anchors,key=lambda anchor:(group_scores[tuple(targets[anchor])],-contrast[anchor]))
        best=np.full(patch.shape[:2],np.inf,dtype=np.float32)
        coverage=np.zeros(patch.shape[:2],dtype=np.float32)
        mapped=np.zeros_like(patch)
        signal=np.maximum(np.sum((patch-bg)**2,axis=2),1)
        # Entre tons que a pessoa uniu, prefira a tinta mais sólida. Isso
        # impede que uma borda clara vire um traço grosso ao ser unida ao azul.
        for anchor in ordered:
            direction=colors[anchor]-bg
            alpha=np.clip(np.sum((patch-bg)*direction,axis=2)/contrast[anchor],0,1)
            # Normalize pela força do traço: nas bordas bem claras, um erro
            # absoluto pequeno pode trocar a família azul pela família roxa.
            error=np.sum((patch-(bg+alpha[:,:,None]*direction))**2,axis=2)/signal
            better=error<best-.0025
            best[better]=error[better]
            coverage[better]=alpha[better]
            mapped[better]=targets[anchor]
        candidate=output[y0:y1,x0:x1].copy()
        if remove_bg:
            candidate[:,:,:3]=np.uint8(np.clip(mapped,0,255))
            candidate[:,:,3]=np.uint8(np.clip(coverage*raw[y0:y1,x0:x1,3],0,255))
            if np.ptp(bg)>45:
                candidate[:,:,3]=np.minimum(candidate[:,:,3],prepared_alpha[y0:y1,x0:x1])
            # Ilhas brancas internas continuam protegidas pela opção original.
            protected=(prepared_alpha[y0:y1,x0:x1]>240)&(np.max(np.abs(patch-bg),axis=2)<8)
            region&=~protected
        else:
            candidate[:,:,:3]=np.uint8(np.clip(background_target+coverage[:,:,None]*(mapped-background_target),0,255))
            candidate[:,:,3]=raw[y0:y1,x0:x1,3]
        output[y0:y1,x0:x1][region]=candidate[region]
    return Image.fromarray(output,'RGBA')


def clean_interpolation_residue(image, native_alpha):
    """Limpa fragmentos novos do JPEG, mantendo componentes existentes na origem.

    Cada ponto ou acento original guarda seu próprio componente. Só fragmentos
    pequenos adicionais, separados de uma forma que já está representada,
    são descartados; não há um filtro de tamanho global sobre a arte original.
    """
    output=np.asarray(image).copy()
    _,native_labels=cv2.connectedComponents(np.uint8(native_alpha>=128),connectivity=8)
    reference=cv2.resize(native_labels,(image.width,image.height),interpolation=cv2.INTER_NEAREST)
    count,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(output[:,:,3]>32),connectivity=8)
    owners={}
    for label in range(1,count):
        x,y,width,height,_=stats[label]
        local=labels[y:y+height,x:x+width]==label
        sources,amounts=np.unique(reference[y:y+height,x:x+width][local],return_counts=True)
        for source,amount in zip(sources,amounts):
            if source and amount>owners.get(source,(0,0))[1]:
                owners[source]=(label,amount)
    original_components={owner[0] for owner in owners.values()}
    factor=image.width/native_alpha.shape[1]
    small_area=max(1,round(8*factor*factor))
    kept=np.zeros(count,dtype=bool)
    for label in range(1,count):
        kept[label]=stats[label,cv2.CC_STAT_AREA]>small_area or label in original_components
    support=kept[labels]
    # Conserve o antialias contíguo aos componentes válidos, sem deixar a
    # interpolação ressuscitar blocos isolados do fundo comprimido.
    support=cv2.dilate(np.uint8(support),np.ones((3,3),np.uint8)).astype(bool)
    output[~support,3]=0
    return Image.fromarray(output,'RGBA')


def process(img, palette, replacements, bg_mode, bg_color, anywhere, smoothness, keep_thin_details=False):
    # Quantizar na resolução pequena transforma a cobertura parcial das letras
    # em degraus que a vetorização acaba engrossando. Amplie primeiro, enquanto
    # as bordas ainda possuem os tons intermediários da imagem original.
    native=img.convert('RGBA')
    is_jpeg=img.info.get('embimage_source_format')=='JPEG'
    rgba=np.asarray(native).copy()
    if bg_mode != BACKGROUNDS[0]:
        bg_color=color_at_corner(img) if bg_mode==BACKGROUNDS[1] or bg_color is None else bg_color
        if is_jpeg:
            rgba=remove_background(rgba,bg_color,BACKGROUND_TOLERANCE,anywhere)
            rgba=refine_neutral_jpeg_matte(rgba,bg_color)
    native_alpha=rgba[:,:,3].copy()
    # Faça a máscara antes da interpolação: o Lanczos pode criar tons que
    # não existiam no JPG e fazê-los escapar da identificação por matiz.
    foreground=Image.fromarray(rgba,'RGBA')
    source=native
    factor=OUTPUT_MAX_SIDE/max(source.size)
    size=(max(1,round(source.width*factor)),max(1,round(source.height*factor)))
    if source.size != size:
        source=source.resize(size,Image.Resampling.LANCZOS)
        foreground=foreground.resize(size,Image.Resampling.LANCZOS)
    rgba=np.asarray(foreground).copy()
    if bg_mode!=BACKGROUNDS[0] and not is_jpeg:
        rgba=remove_background(rgba,bg_color,BACKGROUND_TOLERANCE,anywhere)
    prepared_alpha=rgba[:,:,3].copy()
    if not keep_thin_details:
        rgba[:,:,:3]=cv2.bilateralFilter(rgba[:,:,:3],5,38,38)
    rgba=apply_palette(rgba,palette,replacements)
    if is_jpeg and bg_mode!=BACKGROUNDS[0]:
        # O JPEG original é opaco. A transparência intermediária da máscara
        # serve para localizar a borda, não para criar dezenas de regiões de
        # opacidade no traçador. O PNG renderizado recebe antialias novamente.
        trace_alpha=np.where(prepared_alpha>=128,255,0).astype(np.uint8)
        if not keep_thin_details:
            sigma=max(.25,min(6.5,factor*{1:.25,2:.65,3:1.25}[smoothness]))
            trace_alpha=cv2.GaussianBlur(trace_alpha,(0,0),sigma)
        rgba[:,:,3]=np.where(trace_alpha>=128,255,0).astype(np.uint8)
    curve_scale=max(1,min(3,factor*.6)) if is_jpeg else 1.
    traced=vectorize_to_png(rgba,palette,replacements,smoothness,keep_thin_details,curve_scale)
    source_alpha=np.asarray(source)[:,:,3]
    if bg_mode==BACKGROUNDS[0] and np.all(source_alpha==255):
        # A renderização de regiões adjacentes pode deixar costuras com alpha
        # parcial. Uma entrada opaca mantida deve continuar totalmente opaca.
        background=bg_color or color_at_corner(img)
        if palette:
            nearest=min(palette,key=lambda color:sum((a-b)**2 for a,b in zip(color,background)))
            background=replacements.get(nearest,nearest)
        traced=apply_export_background(traced,EXPORT_BACKGROUNDS[3],background).convert('RGBA')
    else:
        # Quantizar as cores não pode tornar uma transparência original opaca.
        pixels=np.asarray(traced).copy()
        pixels[:,:,3]=np.minimum(pixels[:,:,3],source_alpha)
        traced=Image.fromarray(pixels,'RGBA')
    result=restore_delicate_regions(source,prepared_alpha,traced,palette,replacements,
                                   bg_color or color_at_corner(img),bg_mode!=BACKGROUNDS[0],max(6,factor*1.5))
    if bg_mode!=BACKGROUNDS[0] and is_jpeg and not keep_thin_details:
        result=clean_interpolation_residue(result,native_alpha)
    return result


def apply_export_background(img, mode, custom_color):
    """Mantém alpha quando transparente, caso contrário compõe RGB opaco.

    A cor de fundo não entra na contagem de cores do desenho.
    """
    if mode == EXPORT_BACKGROUNDS[1]:
        return img.copy()
    if mode == EXPORT_BACKGROUNDS[0]:
        color = (255, 255, 255)
    elif mode == EXPORT_BACKGROUNDS[2]:
        color = (0, 0, 0)
    else:
        color = custom_color
    base = Image.new('RGBA', img.size, tuple(color)+(255,))
    base.alpha_composite(img.convert('RGBA'))
    return base.convert('RGB')


class App(EmbImageApp):
    def __init__(self, root):
        super().__init__(root, processor=sys.modules[__name__])


def test_cli():
    # Rode: python melhorar_logos.py --demo ENTRADA --out SAIDA
    p=argparse.ArgumentParser();p.add_argument('--demo');p.add_argument('--out',default='resultado.png');args=p.parse_args()
    if args.demo:
        im=load_image(args.demo)
        bg=color_at_corner(im)
        rgba=remove_background(np.asarray(im.convert('RGBA')).copy(),bg,BACKGROUND_TOLERANCE,True)
        palette=detect_palette(rgba)
        r=process(im,palette,{},BACKGROUNDS[1],bg,True,2)
        r.save(args.out)
        print('Arquivo preparado:',args.out,'Fundo selecionado:',bg)
    else:
        root=tk.Tk();App(root);root.mainloop()

if __name__=='__main__':test_cli()
