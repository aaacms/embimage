"""Preparador de Logos v5: interface simplificada, remoção por cor, cor sólida e escolha de fundo na exportação.
Não gera arquivos de pontos nem PES.
"""
from __future__ import annotations
import argparse
from io import BytesIO
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, colorchooser
import cv2
import numpy as np
from PIL import Image, ImageOps, ImageTk, ImageDraw

BACKGROUNDS = ['Não remover', 'Automático (cor do canto)', 'Escolher com clique']
EXPORT_BACKGROUNDS = ['Branco (recomendado para PE-Design)', 'Transparente', 'Preto', 'Cor personalizada']
PALETTE_SIZE = 8
BACKGROUND_TOLERANCE = 45
OUTPUT_MAX_SIDE = 2000
EDGE_SMOOTHNESS = {1: 0.6, 2: 1.3, 3: 2.2}
APP_BACKGROUND = '#f2f2f0'
CARD_BACKGROUND = '#ffffff'
INK = '#171717'
MUTED = '#6f6f6b'


def load_image(path):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert('RGBA')
        if max(im.size) > 4200: im.thumbnail((4200, 4200), Image.Resampling.LANCZOS)
        return im.copy()


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
        val_floor=max(22, float(hsv_c[2]) * (0.48-t/240.0))
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


def vectorize_to_png(rgba, palette, replacements, smoothness, preserve_details=False):
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
    config=vtracer.Config(mode='spline',hierarchical='cutout')
    config.palette=['#%02x%02x%02x' % color for color in target_colors]
    # Com detalhes finos, uma simplificação comum pode eliminar curvas e
    # segmentos de apenas poucos pixels. O valor bem baixo mantém esses
    # segmentos, mas ainda deixa a borda vetorial mais limpa que um raster
    # ampliado diretamente.
    config.simplify=0.08 if preserve_details else EDGE_SMOOTHNESS[smoothness]
    svg=config.convert_bytes(source_bytes.getvalue())
    factor=OUTPUT_MAX_SIDE/max(source.size)
    width=max(1,round(source.width*factor))
    height=max(1,round(source.height*factor))
    svg_string=svg.decode('utf-8') if isinstance(svg,bytes) else svg
    png=resvg_py.svg_to_bytes(svg_string=svg_string,width=width,height=height)
    with Image.open(BytesIO(png)) as result:
        return result.convert('RGBA').copy()


def process(img, palette, replacements, bg_mode, bg_color, anywhere, smoothness, keep_thin_details=False):
    rgba=np.asarray(img.convert('RGBA')).copy()
    if bg_mode != BACKGROUNDS[0]:
        bg_color=color_at_corner(img) if bg_mode==BACKGROUNDS[1] or bg_color is None else bg_color
        rgba=remove_background(rgba,bg_color,BACKGROUND_TOLERANCE,anywhere)
    if not keep_thin_details:
        rgba[:,:,:3]=cv2.bilateralFilter(rgba[:,:,:3],5,38,38)
    elif max(rgba.shape[:2]) < OUTPUT_MAX_SIDE:
        # No modo de detalhes finos, ampliar antes de reduzir a paleta mantém
        # as bordas antisserrilhadas da arte. Fazer o contrário transforma
        # cada pixel original em um degrau muito visível no PNG final.
        factor=OUTPUT_MAX_SIDE/max(rgba.shape[:2])
        size=(max(1,round(rgba.shape[1]*factor)),max(1,round(rgba.shape[0]*factor)))
        rgba=np.asarray(Image.fromarray(rgba,'RGBA').resize(size,Image.Resampling.LANCZOS)).copy()
    rgba=apply_palette(rgba,palette,replacements)
    return vectorize_to_png(rgba,palette,replacements,smoothness,keep_thin_details)


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


class RoundedPanel(tk.Canvas):
    """Cartão leve com cantos arredondados para uma interface menos rígida."""
    def __init__(self, parent, *, padding=18, radius=26, expand_height=False, **kwargs):
        super().__init__(parent,bg=APP_BACKGROUND,highlightthickness=0,bd=0,**kwargs)
        self.padding=padding
        self.radius=radius
        self.expand_height=expand_height
        self.content=tk.Frame(self,bg=CARD_BACKGROUND)
        self.window=self.create_window((padding,padding),window=self.content,anchor='nw')
        self.content.bind('<Configure>',self._fit_content)
        self.bind('<Configure>',self._redraw)

    def _redraw(self,event=None):
        width=max(1,self.winfo_width())
        height=max(1,self.winfo_height())
        r=min(self.radius,width//2,height//2)
        self.delete('card')
        self.create_rectangle(r,0,width-r,height,fill=CARD_BACKGROUND,outline='',tags='card')
        self.create_rectangle(0,r,width,height-r,fill=CARD_BACKGROUND,outline='',tags='card')
        for x,y in ((r,r),(width-r,r),(r,height-r),(width-r,height-r)):
            self.create_oval(x-r,y-r,x+r,y+r,fill=CARD_BACKGROUND,outline='',tags='card')
        self.tag_lower('card')
        self.coords(self.window,self.padding,self.padding)
        self.itemconfigure(self.window,width=max(1,width-self.padding*2))
        if self.expand_height:
            self.itemconfigure(self.window,height=max(1,height-self.padding*2))

    def _fit_content(self,_event=None):
        if not self.expand_height:
            self.configure(height=self.content.winfo_reqheight()+self.padding*2)


class App:
    """Interface simplificada: abrir -> escolher visual -> salvar.

    O motor de tratamento da v3 continua inalterado.
    """
    def __init__(self, root):
        self.root = root
        root.title('Preparador de Logos para Bordado — v5')
        root.geometry('1190x750')
        root.minsize(1000, 650)
        root.configure(bg=APP_BACKGROUND)
        self.original = None
        self.output = None
        self.path = None
        self.job = 0
        self._scheduled = None
        self._preview_bounds = None
        self.chosen_bg = None
        self.custom_bg = (255, 255, 255)
        self.palette = []
        self.color_replacements = {}
        self.palette_rows = None
        self._palette_scheduled = None
        self.remove_bg = tk.BooleanVar(value=True)
        self.bg_mode = tk.StringVar(value=BACKGROUNDS[1])
        self.anywhere = tk.BooleanVar(value=True)
        self.export_bg = tk.StringVar(value=EXPORT_BACKGROUNDS[0])
        self.palette_size = tk.IntVar(value=PALETTE_SIZE)
        self.edge_smoothness = tk.IntVar(value=2)
        self.keep_thin_details = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Passo 1 de 6: abra uma imagem para começar.')
        self.bg_hint = tk.StringVar(value='Automático: usa a cor dos cantos da imagem.')
        self.build()
        root.bind('<Control-o>', lambda e:self.open_file())
        root.bind('<Control-s>', lambda e:self.save_png())

    def build(self):
        style = ttk.Style()
        try: style.theme_use('clam')
        except tk.TclError: pass
        style.configure('TFrame',background=APP_BACKGROUND)
        style.configure('TLabel',font=('Segoe UI',10),background=APP_BACKGROUND,foreground=INK)
        style.configure('Card.TLabel',font=('Segoe UI',10),background=CARD_BACKGROUND,foreground=INK)
        style.configure('CardMuted.TLabel',font=('Segoe UI',10),background=CARD_BACKGROUND,foreground=MUTED)
        style.configure('TButton',font=('Segoe UI',10,'bold'),padding=(13,9),background=CARD_BACKGROUND,foreground=INK,borderwidth=0)
        style.map('TButton',background=[('active','#e9e9e6'),('pressed','#deded9')])
        style.configure('Primary.TButton',font=('Segoe UI',10,'bold'),padding=(16,10),foreground='white',background=INK,borderwidth=0)
        style.map('Primary.TButton',background=[('active','#333333'),('pressed','#000000')])
        style.configure('Count.TButton',font=('Segoe UI',13,'bold'),padding=(6,0),background='#f2f2f0')
        style.configure('Count.TLabel',font=('Segoe UI',12,'bold'),anchor='center',background=CARD_BACKGROUND)
        header = tk.Frame(self.root,bg=APP_BACKGROUND,height=88)
        header.pack(fill='x');header.pack_propagate(False)
        tk.Label(header,text='◼',bg=APP_BACKGROUND,fg=INK,font=('Segoe UI',18,'bold')).pack(side='left',padx=(28,12))
        header_text=tk.Frame(header,bg=APP_BACKGROUND)
        header_text.pack(side='left',fill='y',pady=19)
        tk.Label(header_text,text='EmbImage',bg=APP_BACKGROUND,fg=INK,font=('Segoe UI',16,'bold')).pack(anchor='w')
        tk.Label(header_text,text='Prepare logos para bordado',bg=APP_BACKGROUND,fg=MUTED,font=('Segoe UI',9)).pack(anchor='w',pady=(2,0))

        top=ttk.Frame(self.root,padding=(17,12));top.pack(fill='x')
        open_group=ttk.Frame(top);open_group.pack(side='left')
        self.step_badge(open_group,'1').pack(side='left',padx=(0,8))
        ttk.Button(open_group,text='Abrir imagem...',style='Step.TButton',command=self.open_file).pack(side='left')
        self.file_label=ttk.Label(top,text='Nenhuma imagem selecionada',foreground=MUTED)
        self.file_label.pack(side='left',padx=8)
        save_group=ttk.Frame(top);save_group.pack(side='right')
        self.step_badge(save_group,'6',primary=True).pack(side='left',padx=(0,8))
        ttk.Button(save_group,text='Salvar PNG',style='Primary.TButton',command=self.save_png).pack(side='left')

        body=tk.Frame(self.root,bg=APP_BACKGROUND)
        body.pack(fill='both',expand=True,padx=22,pady=(0,12))
        # A coluna esquerda é rolável: na V4, as opções avançadas eram
        # exibidas fora da área visível e pareciam não funcionar.
        sidebar=tk.Frame(body,bg=APP_BACKGROUND,width=335)
        sidebar.pack(side='left',fill='y',padx=(0,15))
        sidebar.pack_propagate(False)
        sidebar_canvas=tk.Canvas(sidebar,bg=APP_BACKGROUND,highlightthickness=0,bd=0)
        sidebar_scroll=ttk.Scrollbar(sidebar,orient='vertical',command=sidebar_canvas.yview)
        sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        sidebar_scroll.pack(side='right',fill='y')
        sidebar_canvas.pack(side='left',fill='both',expand=True)
        left=tk.Frame(sidebar_canvas,bg=APP_BACKGROUND)
        window=sidebar_canvas.create_window((0,0),window=left,anchor='nw')
        self.sidebar_canvas=sidebar_canvas
        def update_scroll(_event=None):
            sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox('all'))
        def fit_width(event):
            sidebar_canvas.itemconfigure(window,width=max(200,event.width))
        left.bind('<Configure>',update_scroll)
        sidebar_canvas.bind('<Configure>',fit_width)
        def wheel(event):
            if sidebar_canvas.winfo_exists():
                sidebar_canvas.yview_scroll(-int(event.delta / 120) if event.delta else 0,'units')
                return 'break'
        def wheel_enter(_event):
            sidebar_canvas.bind_all('<MouseWheel>',wheel)
        def wheel_leave(_event):
            sidebar_canvas.unbind_all('<MouseWheel>')
        sidebar_canvas.bind('<Enter>',wheel_enter)
        sidebar_canvas.bind('<Leave>',wheel_leave)
        left.bind('<Enter>',wheel_enter)

        palette_card=RoundedPanel(left,padding=18)
        palette_card.pack(fill='x',pady=(2,12))
        palette_inner=palette_card.content
        self.card_title(palette_inner,'4','Ajuste as cores').pack(anchor='w',pady=(0,7))
        ttk.Label(palette_inner,text='Escolha as cores que realmente serão usadas no bordado.',style='CardMuted.TLabel',wraplength=267).pack(anchor='w',pady=(0,14))
        ttk.Label(palette_inner,text='Quantidade de cores',style='Card.TLabel').pack(anchor='w')
        color_count=tk.Frame(palette_inner,bg=CARD_BACKGROUND)
        color_count.pack(anchor='w',pady=(3,4))
        ttk.Button(color_count,text='−',style='Count.TButton',width=3,command=lambda:self.change_palette_size(-1)).pack(side='left')
        ttk.Label(color_count,textvariable=self.palette_size,style='Count.TLabel',width=4).pack(side='left',padx=5)
        ttk.Button(color_count,text='+',style='Count.TButton',width=3,command=lambda:self.change_palette_size(1)).pack(side='left')
        ttk.Label(palette_inner,text='Use menos cores para um logo mais simples. Alterar esse número refaz as trocas atuais.',style='CardMuted.TLabel',wraplength=267).pack(anchor='w',pady=(0,12))
        self.palette_rows=tk.Frame(palette_inner,bg=CARD_BACKGROUND)
        self.palette_rows.pack(fill='x')
        self.palette_empty=ttk.Label(self.palette_rows,text='Abra uma imagem para identificar as cores.',style='CardMuted.TLabel',wraplength=267)
        self.palette_empty.pack(anchor='w')

        edge_card=RoundedPanel(left,padding=18)
        edge_card.pack(fill='x',pady=(0,12))
        edge_inner=edge_card.content
        self.card_title(edge_inner,'5','Qualidade das bordas').pack(anchor='w',pady=(0,3))
        ttk.Label(edge_inner,text='Suavidade das bordas',style='Card.TLabel',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=(12,0))
        edge_control=tk.Frame(edge_inner,bg=CARD_BACKGROUND)
        edge_control.pack(anchor='w',pady=(3,4))
        ttk.Button(edge_control,text='−',style='Count.TButton',width=3,command=lambda:self.change_edge_smoothness(-1)).pack(side='left')
        ttk.Label(edge_control,textvariable=self.edge_smoothness,style='Count.TLabel',width=4).pack(side='left',padx=5)
        ttk.Button(edge_control,text='+',style='Count.TButton',width=3,command=lambda:self.change_edge_smoothness(1)).pack(side='left')
        ttk.Label(edge_inner,text='1 preserva mais detalhes; 3 deixa as curvas mais suaves. A imagem salva terá até 2000 px no maior lado.',style='CardMuted.TLabel',wraplength=267).pack(anchor='w')

        self.details_adv_button=ttk.Button(left,text='⚙  Opções avançadas  ▾',command=self.toggle_advanced)
        self.details_adv_button.pack(fill='x',pady=(0,7))
        self.details_adv=RoundedPanel(left,padding=18)
        adv_inner=self.details_adv.content
        ttk.Label(adv_inner,text='Detalhes finos',style='Card.TLabel',font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(0,6))
        ttk.Checkbutton(adv_inner,text='Preservar detalhes finos',variable=self.keep_thin_details,command=self.queue).pack(anchor='w')
        ttk.Label(adv_inner,text='Indicado para linhas estreitas, letras pequenas e desenhos delicados. Usa uma vetorização bem precisa para manter os traços sem aspecto pixelado.',style='CardMuted.TLabel',wraplength=267).pack(anchor='w',pady=(6,0))

        self.adv=RoundedPanel(left,padding=18)
        adv_inner=self.adv.content
        self.adv.pack(fill='x',pady=(2,12),before=palette_card)
        self.card_title(adv_inner,'2','Escolha a cor do fundo').pack(anchor='w',pady=(0,7))
        ttk.Label(adv_inner,text='O programa detecta a cor dos cantos automaticamente. Se não for o fundo certo, clique no botão e depois sobre o fundo na imagem original.',style='CardMuted.TLabel',wraplength=267).pack(anchor='w',pady=(0,10))
        bgcard=tk.Frame(adv_inner,bg=CARD_BACKGROUND)
        bgcard.pack(fill='x',pady=(0,10))
        self.card_title(bgcard,'3','Manter ou mudar o fundo?').pack(anchor='w',pady=(0,7))
        ttk.Checkbutton(bgcard,text='Manter a cor de fundo original',variable=self.remove_bg,offvalue=True,onvalue=False,command=self.toggle_remove).pack(anchor='w')
        self.pick_btn=ttk.Button(bgcard,text='Escolher a cor clicando na imagem original',command=self.enable_click_pick)
        self.pick_btn.pack(fill='x',pady=(7,3))
        ttk.Label(bgcard,textvariable=self.bg_hint,style='CardMuted.TLabel',wraplength=245).pack(anchor='w',pady=(0,8))
        ttk.Label(bgcard,text='Se mudar, colocar no lugar:',style='Card.TLabel').pack(anchor='w')
        self.bg_picker=ttk.Combobox(bgcard,state='readonly',textvariable=self.export_bg,values=EXPORT_BACKGROUNDS,width=31)
        self.bg_picker.pack(fill='x',pady=(4,6))
        self.bg_picker.bind('<<ComboboxSelected>>',lambda e:self.choose_export_option())
        self.color_bg_btn=ttk.Button(bgcard,text='Escolher uma cor personalizada...',command=self.pick_export_bg)
        self.color_bg_btn.pack(fill='x')
        ttk.Checkbutton(adv_inner,text='Remover cor também em áreas internas',variable=self.anywhere,command=self.queue).pack(anchor='w',pady=(0,5))
        ttk.Label(left,text='Passo 6: quando terminar, clique em “Salvar PNG” no topo.',foreground=MUTED,wraplength=290).pack(anchor='w',pady=(0,5))

        preview_card=RoundedPanel(body,padding=22,expand_height=True)
        preview_card.pack(side='left',fill='both',expand=True)
        right=preview_card.content
        ttk.Label(right,text='Prévia do resultado',style='Card.TLabel',font=('Segoe UI',15,'bold')).pack(anchor='w',pady=(3,2))
        ttk.Label(right,text='Compare a imagem original com a versão pronta para bordado antes de salvar.',style='CardMuted.TLabel').pack(anchor='w',pady=(0,16))
        columns=tk.Frame(right,bg=CARD_BACKGROUND);columns.pack(fill='both',expand=True)
        self.labels=[]
        for title in ('Imagem original','Imagem preparada'):
            column=tk.Frame(columns,bg=CARD_BACKGROUND);column.pack(side='left',fill='both',expand=True,padx=5)
            ttk.Label(column,text=title,style='Card.TLabel',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=(0,7))
            label=tk.Label(column,text='Abra uma imagem para começar',bg='#f5f5f3',fg=MUTED,bd=0,relief='flat')
            label.pack(fill='both',expand=True)
            label.bind('<Configure>',lambda e:self.refresh())
            self.labels.append(label)
        self.labels[0].bind('<Button-1>',self.pick_background)
        ttk.Label(right,text='Dica: no passo 2, clique em “Escolher a cor” e depois sobre o fundo na imagem original.',style='CardMuted.TLabel',wraplength=780).pack(anchor='w',pady=(14,0))
        ttk.Label(self.root,textvariable=self.status,padding=(28,8),foreground=MUTED).pack(fill='x')

    @staticmethod
    def step_badge(parent, number, primary=False):
        color=INK if primary else '#e7e7e3'
        foreground='white' if primary else INK
        return tk.Label(parent,text=number,bg=color,fg=foreground,font=('Segoe UI',12,'bold'),width=2,height=1,justify='center',relief='flat')

    def card_title(self, parent, number, title):
        heading=tk.Frame(parent,bg=CARD_BACKGROUND)
        self.step_badge(heading,number,primary=True).pack(side='left',padx=(0,9))
        tk.Label(heading,text=title,bg=CARD_BACKGROUND,fg=INK,font=('Segoe UI',12,'bold')).pack(side='left')
        return heading

    @staticmethod
    def color_text(color):
        return '#%02X%02X%02X' % color

    def render_palette(self):
        for child in self.palette_rows.winfo_children():
            child.destroy()
        if not self.palette:
            ttk.Label(self.palette_rows,text='Nenhuma cor visível encontrada.',style='CardMuted.TLabel').pack(anchor='w')
            return
        for source in self.palette:
            target=self.color_replacements.get(source,source)
            row=tk.Frame(self.palette_rows,bg=CARD_BACKGROUND)
            row.pack(fill='x',pady=2)
            tk.Label(row,bg=self.color_text(source),width=2,height=1,relief='solid',bd=1).pack(side='left',padx=(0,6))
            label=self.color_text(source)
            if target!=source:
                label += '  →  ' + self.color_text(target)
            ttk.Button(row,text=label,command=lambda color=source:self.choose_palette_color(color)).pack(side='left',fill='x',expand=True)

    def update_palette(self):
        if self.original is None:
            return
        rgba=np.asarray(self.original.convert('RGBA')).copy()
        if self.remove_bg.get():
            bg=self.chosen_bg if self.bg_mode.get()==BACKGROUNDS[2] else color_at_corner(self.original)
            rgba=remove_background(rgba,bg,BACKGROUND_TOLERANCE,self.anywhere.get())
        self.palette=detect_palette(rgba,self.palette_size.get())
        self.color_replacements={}
        self.render_palette()

    def schedule_palette_update(self):
        if self.original is None:
            return
        if self._palette_scheduled is not None:
            self.root.after_cancel(self._palette_scheduled)
        self._palette_scheduled=self.root.after(300,self.apply_palette_size)

    def change_palette_size(self, amount):
        current=self.palette_size.get()
        updated=max(2,min(12,current+amount))
        if updated != current:
            self.palette_size.set(updated)
            self.schedule_palette_update()

    def change_edge_smoothness(self, amount):
        current=self.edge_smoothness.get()
        updated=max(1,min(3,current+amount))
        if updated != current:
            self.edge_smoothness.set(updated)
            self.queue()

    def apply_palette_size(self):
        self._palette_scheduled=None
        self.update_palette()
        self.queue()

    def choose_palette_color(self, source):
        """Permite unir uma cor somente a outra cor detectada na imagem."""
        dialog=tk.Toplevel(self.root)
        dialog.title('Unir cores')
        dialog.transient(self.root)
        dialog.resizable(False,False)
        dialog.grab_set()
        frame=ttk.Frame(dialog,padding=16)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=f'Para qual cor deseja trocar {self.color_text(source)}?',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=(0,5))
        ttk.Label(frame,text='Escolha uma das cores já encontradas nesta imagem.',foreground='#556777').pack(anchor='w',pady=(0,12))

        def apply(target):
            self.color_replacements[source]=target
            self.render_palette()
            self.queue()
            dialog.destroy()

        for target in self.palette:
            if target==source:
                continue
            row=ttk.Frame(frame)
            row.pack(fill='x',pady=3)
            tk.Label(row,bg=self.color_text(target),width=3,height=1,relief='solid',bd=1).pack(side='left',padx=(0,8))
            ttk.Button(row,text=self.color_text(target),command=lambda color=target:apply(color)).pack(side='left',fill='x',expand=True)

        if source in self.color_replacements:
            ttk.Button(frame,text='Desfazer troca desta cor',command=lambda:(self.color_replacements.pop(source),self.render_palette(),self.queue(),dialog.destroy())).pack(fill='x',pady=(10,0))
        ttk.Button(frame,text='Cancelar',command=dialog.destroy).pack(fill='x',pady=(6,0))

    def toggle_remove(self):
        if self.remove_bg.get() and self.bg_mode.get()==BACKGROUNDS[0]:self.bg_mode.set(BACKGROUNDS[1])
        self.update_palette()
        self.queue()

    def ask_keep_background(self):
        """Confirma o passo 3 sem esconder a escolha de fundo na interface."""
        keep=messagebox.askyesno(
            'Passo 3 de 6: fundo final',
            'Você quer manter a cor de fundo original na imagem final?\n\n'
            'Escolha “Não” para retirar o fundo e selecionar uma nova opção.'
        )
        self.remove_bg.set(not keep)
        self.update_palette()
        self.status.set('Passo 4 de 6: mantenha as cores ou clique em uma delas para trocá-la.')
        self.queue()

    def enable_click_pick(self):
        if self.original is None:
            messagebox.showinfo('Abra uma imagem','Primeiro, clique em “Abrir imagem”.');return
        self.remove_bg.set(True)
        self.bg_mode.set(BACKGROUNDS[2]);self.bg_hint.set('Agora clique sobre o fundo na imagem ORIGINAL, à direita.')
        self.status.set('Passo 2 de 6: clique na cor do fundo na imagem original.')
        self.queue()

    def choose_export_option(self):
        if self.export_bg.get()==EXPORT_BACKGROUNDS[3]:self.pick_export_bg()
        else:self.refresh()

    def toggle_advanced(self):
        if self.details_adv.winfo_manager():
            self.details_adv.pack_forget()
            self.details_adv_button.configure(text='⚙  Opções avançadas  ▾')
        else:
            self.details_adv.pack(fill='x',pady=(0,10),after=self.details_adv_button)
            self.details_adv_button.configure(text='⚙  Menos opções  ▴')

    def pick_background(self,event):
        if self.original is None or not self._preview_bounds:return
        px,py,pw,ph=self._preview_bounds
        if not(px<=event.x<px+pw and py<=event.y<py+ph):return
        x=min(self.original.width-1,max(0,int((event.x-px)*self.original.width/pw)))
        y=min(self.original.height-1,max(0,int((event.y-py)*self.original.height/ph)))
        a=np.asarray(self.original)[:,:,:3]
        sample=a[max(0,y-2):y+3,max(0,x-2):x+3]
        self.chosen_bg=tuple(int(n) for n in np.median(sample.reshape(-1,3),axis=0))
        self.bg_mode.set(BACKGROUNDS[2]);self.remove_bg.set(True)
        self.bg_hint.set('Cor escolhida: #%02X%02X%02X. Clique novamente para mudar.'%self.chosen_bg)
        self.ask_keep_background()

    def pick_export_bg(self):
        rgb,code=colorchooser.askcolor(color='#%02x%02x%02x'%self.custom_bg,title='Cor final do fundo')
        if rgb is not None:
            self.custom_bg=tuple(int(round(x)) for x in rgb)
            self.export_bg.set(EXPORT_BACKGROUNDS[3]);self.refresh()
        elif self.export_bg.get()==EXPORT_BACKGROUNDS[3]:
            self.refresh()

    def open_file(self):
        f=filedialog.askopenfilename(filetypes=[('Imagens PNG, JPG, WEBP','*.png *.jpg *.jpeg *.webp *.bmp'),('Todos os arquivos','*.*')])
        if not f:return
        try:
            self.original=load_image(f);self.path=f;self.chosen_bg=color_at_corner(self.original)
            self.bg_mode.set(BACKGROUNDS[1]);self.remove_bg.set(True)
            self.bg_hint.set('Automático: cor dos cantos. Se não ficar bom, clique na imagem original.')
            self.file_label.configure(text=Path(f).name)
            color='#%02X%02X%02X' % self.chosen_bg
            confirmed=messagebox.askyesno(
                'Passo 2 de 6: cor do fundo',
                f'O programa identificou {color} nos cantos da imagem. Essa é a cor do fundo?\n\n'
                'Escolha “Não” para clicar na cor correta na prévia original.'
            )
            if confirmed:
                self.ask_keep_background()
            else:
                self.enable_click_pick()
        except Exception as ex:messagebox.showerror('Erro ao abrir',str(ex))

    def queue(self):
        if self.original is None:return
        if self._scheduled is not None:self.root.after_cancel(self._scheduled)
        self._scheduled=self.root.after(300,self.start)

    def start(self):
        self._scheduled=None;self.job+=1;job=self.job
        bgmode=(self.bg_mode.get() if self.remove_bg.get() else BACKGROUNDS[0])
        args=(self.palette,self.color_replacements,bgmode,self.chosen_bg,self.anywhere.get(),self.edge_smoothness.get(),self.keep_thin_details.get())
        img=self.original.copy();self.status.set('Preparando a imagem...')
        def worker():
            try:
                result=process(img,*args)
                self.root.after(0,lambda:self.finish(job,result,None))
            except Exception as ex:
                self.root.after(0,lambda:self.finish(job,None,str(ex)))
        threading.Thread(target=worker,daemon=True).start()

    def finish(self,job,result,err):
        if job!=self.job:return
        if err:self.status.set('Erro ao preparar: '+err);return
        self.output=result
        self.status.set(f'Pronto para salvar · {result.width} × {result.height} pixels · PNG recomendado para PE-Design Next')
        self.refresh()

    def refresh(self):
        if self.original is None:return
        for i,im in enumerate((self.original,self.output)):
            if im is None:continue
            label=self.labels[i];lw=max(100,label.winfo_width());lh=max(100,label.winfo_height())
            p=im.copy();p.thumbnail((max(10,lw-24),max(10,lh-24)),Image.Resampling.LANCZOS)
            if i==1 and self.export_bg.get()!=EXPORT_BACKGROUNDS[1]:
                image=apply_export_background(p,self.export_bg.get(),self.custom_bg).convert('RGB')
            else:
                backdrop=Image.new('RGBA',p.size,'white');draw=ImageDraw.Draw(backdrop);s=14
                for y in range(0,p.height,s):
                    for x in range(0,p.width,s):
                        if ((x//s+y//s)%2)==1:draw.rectangle((x,y,x+s-1,y+s-1),fill='#e8e8e8')
                backdrop.alpha_composite(p.convert('RGBA'))
                image=backdrop.convert('RGB')
            photo=ImageTk.PhotoImage(image)
            label.configure(image=photo,text='');label.image=photo
            if i==0:self._preview_bounds=((lw-p.width)//2,(lh-p.height)//2,p.width,p.height)

    def save_png(self):
        if self.output is None:messagebox.showinfo('Falta imagem','Primeiro, abra uma imagem.');return
        dst=filedialog.asksaveasfilename(defaultextension='.png',initialfile=Path(self.path).stem+'_para_bordado.png',filetypes=[('PNG','*.png')])
        if not dst:return
        try:
            apply_export_background(self.output,self.export_bg.get(),self.custom_bg).save(dst,'PNG')
            self.status.set('Imagem salva: '+dst)
            messagebox.showinfo('Imagem salva','Tudo pronto! Agora você pode abrir este PNG no PE-Design Next.')
        except Exception as ex:messagebox.showerror('Erro ao salvar',str(ex))

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
