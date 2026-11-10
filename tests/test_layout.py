"""Valida os controles visíveis com Tk real em diferentes tamanhos e escalas."""
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest

from PIL import Image, ImageDraw, ImageGrab

from test_workflow import processor


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / 'Atelie - flores e folhas.png'
        image = Image.new('RGB', (460, 360), '#FFF9F0')
        draw = ImageDraw.Draw(image)
        draw.ellipse((100, 40, 235, 175), fill='#E99787')
        draw.ellipse((225, 40, 360, 175), fill='#C95B64')
        draw.ellipse((100, 160, 235, 295), fill='#C95B64')
        draw.ellipse((225, 160, 360, 295), fill='#E99787')
        draw.ellipse((193, 128, 267, 202), fill='#E4B353')
        draw.line((230, 225, 230, 330), fill='#267B62', width=9)
        draw.ellipse((237, 270, 312, 310), fill='#267B62')
        image.save(self.source)
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.app = None

    def tearDown(self):
        if self.app is not None:
            self.app.close()
        else:
            self.root.destroy()
        self.temp.cleanup()
        self.assertFalse(self.errors, self.errors)

    def settle(self, seconds=.3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)

    def build(self, scaling, width, height):
        self.root.tk.call('tk', 'scaling', scaling)
        self.app = processor.App(self.root)
        width = min(width, self.root.winfo_screenwidth() - 50)
        height = min(height, self.root.winfo_screenheight() - 90)
        self.root.geometry(f'{width}x{height}+20+20')
        self.settle()

    def open_ready(self):
        self.app.open_path(self.source)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and self.app._ready_job != self.app.job:
            self.settle(.05)
        self.assertEqual(self.app._ready_job, self.app.job)
        self.settle()

    def capture(self, name):
        """Só captura a janela do app quando solicitado explicitamente no ambiente."""
        target = os.environ.get('EMBIMAGE_PREVIEW_DIR')
        if target:
            folder = Path(target)
            folder.mkdir(parents=True, exist_ok=True)
            handle = int(self.root.wm_frame(), 16)
            ImageGrab.grab(window=handle).save(folder / f'{name}.png')

    def assert_inside(self, widget, parent):
        self.assertTrue(widget.winfo_ismapped())
        left = widget.winfo_rootx() - parent.winfo_rootx()
        top = widget.winfo_rooty() - parent.winfo_rooty()
        self.assertGreaterEqual(left, 0)
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(left + widget.winfo_width(), parent.winfo_width())
        self.assertLessEqual(top + widget.winfo_height(), parent.winfo_height())

    def test_wide_numbered_steps_and_comparison(self):
        self.build(96 / 72, 1320, 800)
        self.capture('01-inicio')
        self.open_ready()
        for canvas in self.app.canvases:
            self.assert_inside(canvas, self.app.preview)
            self.assertGreater(canvas.winfo_width(), 200)
        self.capture('02-comparacao')
        self.assertEqual([number for number, _ in self.app.numbered_sections], [2, 3, 4, 5])
        self.assertEqual(self.app.open_button.number, '1')
        self.assertEqual(self.app.save_button.number, '6')
        for _, heading in self.app.numbered_sections:
            self.assert_inside(heading, self.app.sidebar)
        # Repetir o layout não pode invalidar permanentemente a área de seleção.
        self.app._layout_previews()
        self.settle()
        self.assertIsNotNone(self.app._preview_bounds)
        self.app.enable_click_pick()
        self.settle()
        self.capture('03-selecionar-fundo')
        self.app.cancel_pick()

    def test_small_window_keeps_controls_accessible(self):
        self.build(96 / 72, 860, 640)
        self.open_ready()
        self.assertTrue(self.app._compact)
        for widget in (self.app.save_button, self.app.open_button, self.app.background_button):
            self.assert_inside(widget, self.root)
        self.assert_inside(self.app.canvases[1], self.app.preview)
        self.assert_inside(self.app.canvases[0], self.app.preview)
        self.capture('04-janela-menor')

    def test_larger_text_and_150_percent_scale(self):
        self.build(2., 1320, 900)
        self.open_ready()
        for widget in (self.app.save_button, self.app.open_button):
            self.assert_inside(widget, self.root)
        self.assert_inside(self.app.canvases[1], self.app.preview)
        self.capture('05-escala-150')

    def test_custom_controls_support_keyboard(self):
        self.build(96 / 72, 1180, 780)
        self.open_ready()
        count = self.app.palette_size.get()
        self.app.plus_button.focus_force()
        self.settle(.1)
        self.app.plus_button.event_generate('<Return>')
        self.settle(.1)
        self.assertEqual(self.app.palette_size.get(), count + 1)
        self.open_ready()


if __name__ == '__main__':
    unittest.main()
