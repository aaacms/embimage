"""Fidelidade de letras e linhas finas usando referência desenhada em alta resolução."""
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from test_workflow import processor

PURPLE = (46, 42, 137)
BLUE = (0, 169, 224)
WHITE = (255, 255, 255)


def serif_font(size):
    for name in ('C:/Windows/Fonts/times.ttf', 'DejaVuSerif.ttf', 'LiberationSerif-Regular.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    raise unittest.SkipTest('Fonte serifada indisponível para a referência de qualidade.')


def make_fixture():
    """O arquivo pequeno simula um logo com hastes de menos de um pixel e serifas."""
    reference = Image.new('RGB', (2000, 1400), WHITE)
    draw = ImageDraw.Draw(reference)
    draw.text((180, 800), 'São Lucas', font=serif_font(350), fill=PURPLE)
    draw.text((385, 625), 'C O M U N I D A D E', font=serif_font(86), fill=BLUE)
    # Hastes, acentos, curvas e detalhes isolados são avaliados separadamente do texto.
    for x, width in ((520, 2), (570, 3), (620, 4), (680, 6)):
        draw.line((x, 250, x, 540), fill=PURPLE, width=width)
    for x, width in ((1180, 2), (1220, 3), (1270, 4), (1340, 6)):
        draw.line((x, 250, x + 20, 540), fill=BLUE, width=width)
    draw.arc((735, 175, 1085, 420), 15, 165, fill=PURPLE, width=4)
    draw.line((895, 100, 895, 550), fill=BLUE, width=7)
    draw.line((850, 160, 940, 160), fill=BLUE, width=4)
    draw.ellipse((920, 105, 925, 110), fill=PURPLE)
    low = reference.resize((500, 350), Image.Resampling.LANCZOS).convert('RGBA')
    return reference.convert('RGBA'), low


def ink_mask(image):
    rgb = np.asarray(processor.apply_export_background(image, processor.EXPORT_BACKGROUNDS[0], WHITE))
    return np.min(rgb, axis=2) < 210


def fidelity(reference, actual, region=None):
    expected, result = ink_mask(reference), ink_mask(actual)
    if region:
        x0, y0, x1, y1 = region
        expected, result = expected[y0:y1, x0:x1], result[y0:y1, x0:x1]
    intersection = np.count_nonzero(expected & result)
    return dict(
        iou=intersection / max(1, np.count_nonzero(expected | result)),
        recall=intersection / max(1, np.count_nonzero(expected)),
        area=np.count_nonzero(result) / max(1, np.count_nonzero(expected)))


def ink_mass(image, region=None):
    """Conta a cobertura parcial das bordas; um pixel claro não equivale a tinta opaca."""
    rgb=np.asarray(processor.apply_export_background(image,processor.EXPORT_BACKGROUNDS[0],WHITE)).astype(float)
    if region:
        x0,y0,x1,y1=region
        rgb=rgb[y0:y1,x0:x1]
    return np.sum(255-rgb)


class ImageQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference, cls.source = make_fixture()
        cls.palette = [PURPLE, BLUE, WHITE]
        cls.results = {
            level: processor.process(cls.source, cls.palette, {}, processor.BACKGROUNDS[1], WHITE, False, level)
            for level in (1, 2, 3)}

    def test_smoothing_preserves_small_serif_letters(self):
        for level, image in self.results.items():
            with self.subTest(level=level):
                score = fidelity(self.reference, image, (300, 620, 1700, 750))
                self.assertGreater(score['iou'], .83, score)
                self.assertLess(abs(score['area'] - 1), .12, score)

    def test_smoothing_preserves_hairlines_and_accents(self):
        for level, image in self.results.items():
            with self.subTest(level=level):
                score = fidelity(self.reference, image, (480, 80, 1390, 565))
                self.assertGreater(score['recall'], .85, score)
                # A referência foi reduzida a 1/4: os traços de meio pixel
                # necessariamente têm bordas parciais. Compare sua cobertura,
                # em vez de contar todo pixel de antialias como tinta sólida.
                region=(480,80,1390,565)
                ratio=ink_mass(image,region)/ink_mass(self.reference,region)
                self.assertLess(abs(ratio-1),.15,ratio)
                for x in (520,570,620,680,1180,1220,1270,1340):
                    self.assertGreater(ink_mass(image,(x-12,300,x+24,500)),50)

    def test_explicit_fine_detail_mode_keeps_shapes(self):
        result = processor.process(self.source, self.palette, {}, processor.BACKGROUNDS[1], WHITE, False, 3, True)
        score = fidelity(self.reference, result)
        self.assertGreater(score['recall'], .97, score)
        self.assertLess(abs(ink_mass(result)/ink_mass(self.reference)-1),.12)

    def test_color_merging_keeps_coverage(self):
        replacements = {BLUE: PURPLE}
        merged = processor.process(self.source, self.palette, replacements,
                                   processor.BACKGROUNDS[1], WHITE, False, 3)
        score = fidelity(self.results[3], merged)
        self.assertGreater(score['iou'], .97, score)

    def test_detected_palette_and_manual_merges_preserve_thin_drawing(self):
        rgba=processor.remove_background(np.asarray(self.source),WHITE,45,False)
        palette=list(dict.fromkeys(processor.detect_palette(rgba,8)))
        purple=min(palette,key=lambda color:np.sum((np.array(color)-PURPLE)**2))
        blue=min(palette,key=lambda color:np.sum((np.array(color)-BLUE)**2))
        background=max(palette,key=lambda color:sum(color))
        replacements={}
        for color in palette:
            direction=np.array(color,dtype=float)-255
            if np.linalg.norm(direction)<32:
                target=background
            else:
                def projection_error(ink):
                    ink=np.array(ink,dtype=float)-255
                    alpha=np.clip(np.dot(direction,ink)/np.dot(ink,ink),0,1)
                    return np.sum((direction-alpha*ink)**2)
                target=purple if projection_error(PURPLE)<projection_error(BLUE) else blue
            if color!=target:
                replacements[color]=target
        result=processor.process(self.source,palette,replacements,processor.BACKGROUNDS[1],WHITE,False,3)
        region=(480,80,1390,565)
        self.assertGreater(fidelity(self.reference,result,region)['recall'],.9)
        self.assertLess(abs(ink_mass(result,region)/ink_mass(self.reference,region)-1),.2)

    def test_existing_translucent_thin_stroke_is_not_made_opaque(self):
        source=Image.new('RGBA',(100,50),(0,0,0,0))
        ImageDraw.Draw(source).line((50,10,50,40),fill=PURPLE+(80,),width=1)
        result=processor.process(source,[PURPLE],{},processor.BACKGROUNDS[1],(0,0,0),False,3)
        alpha=np.asarray(result)[:,:,3]
        self.assertGreater(alpha.max(),50)
        self.assertLess(alpha.max(),120)
        self.assertEqual(alpha[0,0],0)

    def test_keep_original_background_stays_opaque(self):
        result=processor.process(self.source,self.palette,{},processor.BACKGROUNDS[0],WHITE,False,3)
        self.assertEqual(result.getextrema()[3],(255,255))

    def test_explicit_replacement_of_a_real_light_ink_is_respected(self):
        light=(150,148,198)
        red=(190,30,40)
        source=Image.new('RGBA',(200,100),WHITE+(255,))
        draw=ImageDraw.Draw(source)
        draw.rectangle((10,10,50,70),fill=PURPLE)
        draw.line((120,10,120,80),fill=light,width=1)
        draw.rectangle((170,10,190,70),fill=red)
        result=processor.process(source,[PURPLE,light,red,WHITE],{light:red},
                                 processor.BACKGROUNDS[1],WHITE,False,3)
        pixel=result.getpixel((1205,405))
        self.assertGreater(pixel[3],200)
        self.assertLess(np.linalg.norm(np.array(pixel[:3])-red),8)


if __name__ == '__main__':
    unittest.main()
