import math
import unittest

from editor.document import BackgroundLayer, OverlayLayer, TextLayer, ThumbnailDocument
from editor.geometry import (Geometry, ViewTransform, aabb, centered_view, contains, fit_zoom, handle_at,
                             handle_points, hit_test, resize, rotation_from_pointer, snap_move, snap_targets)


class ViewTransformTests(unittest.TestCase):
    def test_zoom_to_canvas_round_trip_and_fit(self):
        for zoom in (0.25, 0.5, 0.75, 1.0, 1.6):
            view = ViewTransform(zoom, 37.0, 12.5)
            for point in ((0, 0), (640, 360), (1280, 720), (13.3, 701.2)):
                back = view.to_doc(*view.to_view(*point))
                self.assertAlmostEqual(point[0], back[0]); self.assertAlmostEqual(point[1], back[1])
            self.assertEqual((10 / zoom, -4 / zoom), view.delta_to_doc(10, -4))
        zoom = fit_zoom(1000, 600)
        self.assertAlmostEqual(min(952 / 1280, 552 / 720), zoom)
        view = centered_view(0.5, 1000, 600)
        self.assertEqual((180.0, 120.0), (view.origin_x, view.origin_y))
        self.assertEqual((24, 24), (centered_view(1.0, 800, 500).origin_x, centered_view(1.0, 800, 500).origin_y))


class ManipulationTests(unittest.TestCase):
    def setUp(self):
        self.document = ThumbnailDocument()
        self.background = self.document.add(BackgroundLayer(width=1280, height=720))
        self.title = self.document.add(TextLayer(text="title", x=100, y=400, width=600, height=200))
        self.plate = self.document.add(OverlayLayer(kind="plate", x=650, y=420, width=300, height=150))

    def test_hit_test_respects_z_order_lock_visibility_and_rotation(self):
        self.assertIs(self.plate, hit_test(self.document, 680, 450))
        self.assertIs(self.title, hit_test(self.document, 300, 450))
        self.assertIsNone(hit_test(self.document, 20, 20))  # locked background is not selectable
        self.assertIs(self.background, hit_test(self.document, 20, 20, include_locked=True))
        self.plate.visible = False
        self.assertIs(self.title, hit_test(self.document, 680, 450))
        self.title.rotation = 90
        # Rotated 600x200 box around (400, 500) now spans x 300..500, y 200..800.
        self.assertTrue(contains(self.title, 400, 230))
        self.assertFalse(contains(self.title, 150, 500))
        x, y, w, h = aabb(self.title)
        self.assertAlmostEqual(200, w); self.assertAlmostEqual(600, h)

    def test_drag_coordinates_through_zoomed_view(self):
        view = ViewTransform(0.5, 100, 50)
        start = view.to_doc(100 + 150, 50 + 225)
        self.assertEqual((300.0, 450.0), start)
        self.assertIs(self.title, hit_test(self.document, *start))
        dx, dy = view.delta_to_doc(20, -10)
        self.title.x += dx; self.title.y += dy
        self.assertEqual((140.0, 380.0), (self.title.x, self.title.y))

    def test_handles_corner_proportional_and_side_resize_keep_opposite_anchor(self):
        view = ViewTransform(1.0, 0, 0)
        points = handle_points(self.title, view)
        self.assertEqual((700.0, 600.0), points["se"])
        self.assertEqual("se", handle_at(self.title, view, 703, 598))
        self.assertEqual("rot", handle_at(self.title, view, *points["rot"]))
        start = Geometry.of(self.title)
        grown, factor = resize(start, "se", 60, 20)
        self.assertAlmostEqual(grown.width / grown.height, 3.0)
        self.assertGreater(factor, 1.0)
        self.assertAlmostEqual((100.0, 400.0), (grown.x, grown.y))
        wider, factor = resize(start, "w", -50, 999)
        self.assertEqual((50.0, 400.0, 650.0, 200.0), (wider.x, wider.y, wider.width, wider.height))
        self.assertEqual(1.0, factor)
        tiny, _ = resize(start, "e", -5000, 0)
        self.assertGreaterEqual(tiny.width, 8)

    def test_resize_of_rotated_layer_keeps_opposite_corner_fixed(self):
        self.title.rotation = 30
        start = Geometry.of(self.title)
        before = self._corner(start, (-1, -1))
        resized, _ = resize(start, "se", 40, 25, proportional=False)
        after = self._corner(resized, (-1, -1))
        self.assertAlmostEqual(before[0], after[0], places=6); self.assertAlmostEqual(before[1], after[1], places=6)

    @staticmethod
    def _corner(geometry, signs):
        cx, cy = geometry.x + geometry.width / 2, geometry.y + geometry.height / 2
        lx, ly = signs[0] * geometry.width / 2, signs[1] * geometry.height / 2
        angle = math.radians(geometry.rotation)
        return cx + lx * math.cos(angle) - ly * math.sin(angle), cy + lx * math.sin(angle) + ly * math.cos(angle)

    def test_rotation_handle_and_shift_snap(self):
        start = Geometry.of(self.title)
        center = (400, 500)
        angle = rotation_from_pointer(start, (center[0], center[1] - 100), (center[0] + 100, center[1]))
        self.assertAlmostEqual(90.0, angle)
        angle = rotation_from_pointer(start, (center[0], center[1] - 100), (center[0] + 30, center[1] - 100), snap=True)
        self.assertEqual(15.0, angle)

    def test_snapping_to_canvas_center_and_other_layers(self):
        targets = snap_targets(self.document, moving_ids={self.title.id})
        dx, dy, guides = snap_move((337, 416, 600, 200), targets, threshold=6)
        self.assertEqual((3.0, 4.0), (dx, dy))  # centre -> 640, top -> plate top
        self.assertIn(("x", 640.0), guides)
        self.assertEqual(("y", 420.0), next(g for g in guides if g[0] == "y"))
        dx, dy, guides = snap_move((500, 100, 10, 10), targets, threshold=2)
        self.assertEqual((0.0, 0.0, []), (dx, dy, guides))


if __name__ == "__main__":
    unittest.main()
