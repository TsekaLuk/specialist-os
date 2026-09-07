"""Real OpenCV calibration and validation regressions."""

import importlib.util
import unittest

from specialist.geometry import GeometryError, calibrate_camera


class CameraCalibrationTests(unittest.TestCase):
    def test_dimensions_alone_never_claim_calibration(self):
        with self.assertRaises(GeometryError):
            calibrate_camera([640, 480])
        with self.assertRaises(GeometryError):
            calibrate_camera([640, 480], [[0, 0, 0]] * 4, [[0, 0]] * 4)

    @unittest.skipUnless(importlib.util.find_spec("cv2"), "OpenCV required for numeric regression")
    def test_recovers_known_camera_from_projected_test_correspondences(self):
        import cv2
        import numpy as np

        board = np.zeros((54, 3), np.float32)
        board[:, :2] = np.mgrid[0:9, 0:6].T.reshape(-1, 2)
        camera = np.array([[800, 0, 320], [0, 810, 240], [0, 0, 1]], np.float64)
        objects, images = [], []
        for i in range(8):
            projected, _ = cv2.projectPoints(board, np.array([.03 * i, .08 - .02 * i, .015 * i]), np.array([-4., -2., 16. + i]), camera, np.zeros(5))
            objects.append(board.tolist())
            images.append(projected.reshape(-1, 2).tolist())
        result = calibrate_camera([640, 480], objects, images)
        self.assertEqual(result["method"], "opencv.calibrateCamera")
        self.assertFalse(result["estimated"])
        self.assertEqual(result["view_count"], 8)
        self.assertLess(result["reprojection_error"], .01)
        np.testing.assert_allclose(result["camera_matrix"], camera, atol=.1)


if __name__ == "__main__":
    unittest.main()
