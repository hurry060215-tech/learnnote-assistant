import importlib.util
from pathlib import Path
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('brand_generator', ROOT / 'scripts/generate-brand-assets.py')
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)


class BrandAssetsTests(unittest.TestCase):
    def test_toolbar_and_desktop_assets_have_correct_sizes_and_clear_corners(self):
        for size in brand.SIZES:
            with self.subTest(size=size):
                path = ROOT / f'assets/brand/learnnote-mark-{size}.png'
                brand.validate_png(path, size)
                with Image.open(path) as image:
                    self.assertEqual(image.getpixel((0, 0))[3], 0)
                    self.assertEqual(image.tobytes(), brand.render_mark(size).tobytes())
                self.assertEqual(path.read_bytes(), (ROOT / f'extension/icons/icon{size}.png').read_bytes())

    def test_current_web_entry_points_use_synchronized_assets(self):
        for size in (32, 128):
            data = (ROOT / f'assets/brand/learnnote-mark-{size}.png').read_bytes()
            self.assertEqual(data, (ROOT / f'web/learnnote-mark-{size}.png').read_bytes())
            self.assertEqual(data, (ROOT / f'site/assets/learnnote-mark-{size}.png').read_bytes())
        self.assertIn('/web/learnnote-mark-128.png', (ROOT / 'web/desk-product.js').read_text(encoding='utf-8'))
        self.assertEqual((ROOT / 'site/index.html').read_text(encoding='utf-8').count('./assets/learnnote-mark-128.png'), 2)

    def test_ico_contains_windows_sizes(self):
        with Image.open(ROOT / 'assets/brand/learnnote.ico') as image:
            self.assertTrue({(n,n) for n in (16,32,48,128,256)}.issubset(image.info['sizes']))


if __name__ == '__main__':
    unittest.main()
