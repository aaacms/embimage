"""Regressões do fluxo de edição. Usa Tk real e não requer novas dependências."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageTk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = SourceFileLoader('embimage_processor', str(ROOT / 'Preparador_de_Logos.pyw'))
spec = spec_from_loader(loader.name, loader)
processor = module_from_spec(spec)
sys.modules[loader.name] = processor
loader.exec_module(processor)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.image_path = Path(cls.temp.name) / 'logo.png'
        image = Image.new('RGB', (180, 140), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((25, 20, 155, 120), fill='#106F60')
        draw.rectangle((60, 50, 120, 90), fill='white')
        draw.line((35, 105, 140, 105), fill='#CB6457', width=3)
        image.save(cls.image_path)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.callback_errors = []
        self.root.report_callback_exception = lambda *error: self.callback_errors.append(error)
        self.app = processor.App(self.root)

    def tearDown(self):
        self.app.close()
        self.assertFalse(self.callback_errors, self.callback_errors)

    def wait_for(self, condition, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(.01)
        self.fail('Tempo esgotado: ' + self.app.status.get())

    def open_ready(self):
        self.app.open_path(self.image_path)
        self.wait_for(lambda: self.app._ready_job == self.app.job)

    def test_open_process_and_export_all_backgrounds(self):
        self.open_ready()
        self.assertEqual(max(self.app.output.size), 2000)
        self.assertFalse(self.app.anywhere.get())
        self.assertTrue(self.app.palette)
        for index, mode in enumerate(processor.EXPORT_BACKGROUNDS):
            self.app.export_bg.set(mode)
            self.app.custom_bg = (30, 90, 170)
            destination = Path(self.temp.name) / f'export-{index}.png'
            with patch('embimage_ui.filedialog.asksaveasfilename', return_value=str(destination)):
                self.app.save_png()
            with Image.open(destination) as result:
                pixel = result.getpixel((0, 0))
                self.assertEqual(result.mode, 'RGBA' if index == 1 else 'RGB')
                if index == 1:
                    self.assertEqual(pixel[3], 0)
                else:
                    self.assertEqual(pixel, ((255, 255, 255), None, (0, 0, 0), (30, 90, 170))[index])

    def test_merge_recount_and_undo(self):
        self.open_ready()
        palette = self.app.palette.copy()
        self.assertGreaterEqual(len(palette), 2)
        self.app.color_replacements[palette[0]] = palette[1]
        self.app._commit()
        self.wait_for(lambda: self.app._ready_job == self.app.job)
        self.app.change_palette_size(-1)
        self.assertEqual(self.app.color_replacements, {})
        self.app.undo()
        self.assertEqual(self.app.palette_size.get(), processor.PALETTE_SIZE)
        self.assertEqual(self.app.color_replacements, {palette[0]: palette[1]})
        self.wait_for(lambda: self.app._ready_job == self.app.job)
        self.assertEqual(self.app.palette, palette)
        self.app.color_replacements.pop(palette[0])
        self.app._commit()
        self.assertEqual(self.app.color_replacements, {})
        self.app.undo()
        self.assertEqual(self.app.color_replacements, {palette[0]: palette[1]})
        self.wait_for(lambda: self.app._ready_job == self.app.job)

    def test_save_is_blocked_immediately_after_edit(self):
        self.open_ready()
        self.app.change_palette_size(-1)
        self.assertTrue(self.app.save_button.instate(['disabled']))
        with patch('embimage_ui.filedialog.asksaveasfilename') as save_dialog:
            self.app.save_png()
            save_dialog.assert_not_called()
        self.wait_for(lambda: self.app._ready_job == self.app.job)
        self.assertFalse(self.app.save_button.instate(['disabled']))

    def test_old_worker_cannot_replace_new_image(self):
        entered, release = threading.Event(), threading.Event()
        original_process = processor.process

        def slow_process(*args):
            entered.set()
            release.wait(5)
            return original_process(*args)

        with patch.object(processor, 'process', side_effect=slow_process):
            self.app.open_path(self.image_path)
            self.wait_for(entered.is_set)
            second_path = Path(self.temp.name) / 'other.png'
            Image.new('RGB', (100, 200), '#A84F3A').save(second_path)
            self.app.open_path(second_path)
            self.assertIsNone(self.app.output)
            release.set()
            self.wait_for(lambda: self.app._ready_job == self.app.job)
        self.assertEqual(self.app.output.size, (1000, 2000))
        self.assertEqual(Path(self.app.path), second_path)

    def test_selection_requires_tool_and_handles_scrolled_coordinates(self):
        self.open_ready()
        old_state = self.app._snapshot()
        event = SimpleNamespace(x=25, y=30)
        self.app.pick_background(event)
        self.assertEqual(self.app._snapshot(), old_state)
        self.app.enable_click_pick()
        self.app._preview_bounds = (0, 0, 180, 140)
        with patch.object(self.app.canvases[0], 'canvasx', return_value=40), patch.object(
                self.app.canvases[0], 'canvasy', return_value=40):
            self.app.pick_background(event)
        self.assertFalse(self.app._picking)
        self.assertEqual(self.app.chosen_bg, (16, 111, 96))
        self.app.undo()
        self.assertEqual(self.app._snapshot(), old_state)
        self.wait_for(lambda: self.app._ready_job == self.app.job)

    def test_cancel_picker_does_not_change_edits(self):
        self.open_ready()
        state = self.app._snapshot()
        self.app.enable_click_pick()
        self.assertTrue(self.app.save_button.instate(['disabled']))
        self.app.cancel_pick()
        self.assertEqual(self.app._snapshot(), state)
        self.assertFalse(self.app.save_button.instate(['disabled']))

    def test_worker_error_retry_and_close(self):
        with patch.object(processor, 'process', side_effect=RuntimeError('Falha de teste')):
            self.app.open_path(self.image_path)
            self.wait_for(lambda: self.app._error is not None)
        self.assertTrue(self.app.save_button.instate(['disabled']))
        self.app.queue()
        self.wait_for(lambda: self.app._ready_job == self.app.job)
        self.assertIsNone(self.app._error)

    def test_border_removal_preserves_enclosed_white_area(self):
        image = processor.load_image(self.image_path)
        rgba = np.asarray(image)
        safe = processor.remove_background(rgba, (255, 255, 255), 45, anywhere=False)
        internal = processor.remove_background(rgba, (255, 255, 255), 45, anywhere=True)
        self.assertEqual(safe[0, 0, 3], 0)
        self.assertEqual(safe[70, 80, 3], 255)
        self.assertEqual(internal[70, 80, 3], 0)

    def test_cancel_custom_color_keeps_previous_option(self):
        self.open_ready()
        old = self.app._snapshot()
        self.app.export_bg.set(processor.EXPORT_BACKGROUNDS[3])
        with patch('embimage_ui.colorchooser.askcolor', return_value=(None, None)):
            self.app.choose_export_option(3)
        self.assertEqual(self.app._snapshot(), old)

    def test_background_button_keeps_menu_alive_and_applies_choices(self):
        self.root.deiconify()
        self.open_ready()
        # tk_popup pode retornar antes da escolha: o menu precisa continuar vivo.
        with patch('embimage_ui.tk.Menu.tk_popup') as popup:
            self.app.background_button._click()
            popup.assert_called_once()
        menus = [child for child in self.root.winfo_children() if isinstance(child, tk.Menu)]
        self.assertEqual(len(menus), 1, 'O menu foi destruído antes de permitir a escolha')
        menu = menus[0]
        for label, expected in (('Preto', (0, 0, 0)), ('Branco', (255, 255, 255)),
                                ('Transparente', None), ('Outra cor…', (30, 90, 170))):
            index = next(i for i in range(menu.index('end') + 1) if menu.entrycget(i, 'label') == label)
            with patch('embimage_ui.colorchooser.askcolor', return_value=((30, 90, 170), '#1e5aaa')):
                menu.invoke(index)
            self.assertEqual(self.app.final_background.get(), label)
            self.assertEqual(self.app.background_button.text, label + '   ▾')
            self.assertEqual(self.app.export_bg.get(), processor.EXPORT_BACKGROUNDS[
                ('Branco', 'Transparente', 'Preto', 'Outra cor…').index(label)])
            result = processor.apply_export_background(self.app.output, self.app.export_bg.get(), self.app.custom_bg)
            if expected is None:
                self.assertEqual(result.getpixel((0, 0))[3], 0)
            else:
                self.assertEqual(result.getpixel((0, 0)), expected)
            self.wait_for(lambda: self.app._refresh_scheduled is None)
            preview = ImageTk.getimage(self.app.photos[1])
            self.assertEqual(preview.getpixel((0, 0))[:3], expected or (255, 255, 255))
            destination = Path(self.temp.name) / 'menu-background.png'
            with patch('embimage_ui.filedialog.asksaveasfilename', return_value=str(destination)):
                self.app.save_png()
            with Image.open(destination) as saved:
                self.assertEqual(saved.getpixel((0, 0)), result.getpixel((0, 0)))
        with patch('embimage_ui.tk.Menu.tk_popup'):
            self.app.background_button._click()
        self.assertEqual([child for child in self.root.winfo_children() if isinstance(child, tk.Menu)], [menu])

    def test_transparent_image_and_invalid_file(self):
        path = Path(self.temp.name) / 'transparent.png'
        Image.new('RGBA', (20, 10), (0, 0, 0, 0)).save(path)
        self.app.open_path(path)
        self.wait_for(lambda: self.app._ready_job == self.app.job)
        self.assertEqual(self.app.palette, [])
        self.assertEqual(self.app.output.getextrema()[3], (0, 0))
        job = self.app.job
        with patch('embimage_ui.messagebox.showerror') as show_error:
            self.app.open_path(Path(self.temp.name) / 'missing.png')
            show_error.assert_called_once()
        self.assertEqual(self.app.job, job)
        self.assertEqual(Path(self.app.path), path)


if __name__ == '__main__':
    unittest.main()
