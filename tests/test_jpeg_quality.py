"""Resíduos de fundo cromático e preservação de pontos reais em logos JPEG."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np
from PIL import Image, ImageDraw

from test_workflow import processor as p


class JpegQualityTests(unittest.TestCase):
    def test_dark_background_shadows_are_removed_but_neutral_ink_is_kept(self):
        rgb=np.uint8([[(161,3,10),(40,3,0),(6,7,7),(81,81,81)]])
        mask=p.color_key_mask(rgb,(161,3,10),45)
        self.assertEqual(mask.tolist(),[[True,True,False,False]])

    def test_cleanup_preserves_original_dot_and_removes_new_isolated_fragments(self):
        native=np.zeros((80,80),dtype=np.uint8)
        native[10:55,10:50]=255
        native[15:17,65:67]=255
        large=cv2.resize(native,(800,800),interpolation=cv2.INTER_NEAREST)
        # Dois resíduos que não representam componentes próprios da origem.
        large[700:705,600:605]=150
        large[510:550,420:500]=0
        large[525:529,440:444]=180
        rgba=np.zeros((800,800,4),dtype=np.uint8)
        rgba[:,:,:3]=7
        rgba[:,:,3]=large
        result=np.asarray(p.clean_interpolation_residue(Image.fromarray(rgba),native))
        self.assertEqual(result[155,655,3],255)
        self.assertEqual(result[702,602,3],0)
        self.assertEqual(result[527,442,3],0)
        self.assertEqual(result[250,250,3],255)

    def test_neutral_matte_keeps_protected_internal_background_region(self):
        source=Image.new('RGBA',(160,160),(161,3,10,255))
        draw=ImageDraw.Draw(source)
        draw.rectangle((20,20,140,140),fill=(7,7,7,255))
        draw.rectangle((70,70,73,73),fill=(161,3,10,255))
        masked=p.remove_background(np.asarray(source),(161,3,10),45,False)
        refined=p.refine_neutral_jpeg_matte(masked,(161,3,10))
        self.assertEqual(refined[71,71,3],255)
        self.assertEqual(refined[0,0,3],0)
        self.assertEqual(refined[40,40,3],255)

    def test_colored_foreground_is_not_treated_as_gray_ink(self):
        source=Image.new('RGBA',(100,100),(161,3,10,255))
        ImageDraw.Draw(source).rectangle((10,10,90,90),fill=(10,160,70,255))
        masked=p.remove_background(np.asarray(source),(161,3,10),45,False)
        self.assertTrue(np.array_equal(masked,p.refine_neutral_jpeg_matte(masked,(161,3,10))))

    def test_real_jpeg_pipeline_keeps_dot_and_has_no_distant_background_dust(self):
        size,scale=240,4
        yy,xx=np.indices((size*scale,size*scale))
        pixels=np.zeros((size*scale,size*scale,3),dtype=np.uint8)
        pixels[:,:,0]=150+np.uint8(xx/(size*scale)*45)
        pixels[:,:,1]=3
        pixels[:,:,2]=10
        source=Image.fromarray(pixels)
        draw=ImageDraw.Draw(source)
        for box in ((25,35,105,220),(135,50,218,215),(112,16,117,21)):
            draw.ellipse(tuple(v*scale for v in box),fill=(7,7,7))
        draw.ellipse((40*scale,55*scale,75*scale,100*scale),fill=(81,81,81))
        source=source.resize((size,size),Image.Resampling.LANCZOS)
        with TemporaryDirectory() as folder:
            path=Path(folder)/'logo.jpg'
            source.save(path,quality=65,subsampling=2)
            loaded=p.load_image(path)
        self.assertEqual(loaded.info['embimage_source_format'],'JPEG')
        background=p.color_at_corner(loaded)
        rgba=p.remove_background(np.asarray(loaded),background,45,False)
        palette=p.detect_palette(rgba,2)
        result=p.process(loaded,palette,{palette[1]:palette[0]},p.BACKGROUNDS[1],background,False,3)
        alpha=np.asarray(result)[:,:,3]
        n,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(alpha>32),connectivity=8)
        self.assertEqual(n-1,3,stats[1:].tolist())
        factor=2000/size
        x,y=round(114*factor),round(18*factor)
        self.assertGreater(alpha[y-8:y+8,x-8:x+8].max(),200)
        self.assertEqual(alpha[:80,:80].max(),0)

    def test_explicit_fine_details_keeps_a_faint_gray_jpeg_line(self):
        source=Image.new('RGB',(100,60),'white')
        ImageDraw.Draw(source).line((50,10,50,50),fill=(200,200,200),width=1)
        with TemporaryDirectory() as folder:
            path=Path(folder)/'fine.jpg'
            source.save(path,quality=95,subsampling=0)
            loaded=p.load_image(path)
        result=p.process(loaded,[(200,200,200)],{},p.BACKGROUNDS[1],(255,255,255),False,3,True)
        alpha=np.asarray(result)[:,:,3]
        self.assertGreater(alpha[300:800,990:1030].max(),150)


if __name__=='__main__':
    unittest.main()
