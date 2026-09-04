"""Validated deterministic geometry helpers used by first-class operators."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any


class GeometryError(ValueError):
    """Raised when geometry input is malformed or cannot be solved."""


class GeometryDependencyError(GeometryError):
    """Raised when a validated operation needs an unavailable local library."""

    code = "dependency_missing"


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise GeometryError(f"{field} must be a finite number")
    return float(value)


def point(value: Any, field: str = "point", dimensions: int | None = None) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) < 2 or len(value) > 3:
        raise GeometryError(f"{field} must contain two or three coordinates")
    if dimensions is not None and len(value) != dimensions:
        raise GeometryError(f"{field} must contain {dimensions} coordinates")
    return tuple(_number(item, f"{field}[{index}]") for index, item in enumerate(value))


def points(values: Any, field: str = "points", minimum: int = 1) -> list[tuple[float, ...]]:
    if not isinstance(values, (list, tuple)) or len(values) < minimum:
        raise GeometryError(f"{field} must contain at least {minimum} points")
    parsed = [point(item, f"{field}[{index}]") for index, item in enumerate(values)]
    dimensions = len(parsed[0])
    if any(len(item) != dimensions for item in parsed):
        raise GeometryError(f"{field} points must use the same dimensions")
    return parsed


def distance(a: Any, b: Any) -> dict[str, Any]:
    first = point(a, "a")
    second = point(b, "b", len(first))
    value = math.sqrt(sum((left - right) ** 2 for left, right in zip(first, second)))
    return {"distance": value, "dimensions": len(first), "deterministic": True}


def angle(a: Any, vertex: Any, c: Any, unit: str = "degrees") -> dict[str, Any]:
    first = point(a, "a")
    middle = point(vertex, "vertex", len(first))
    third = point(c, "c", len(first))
    left = tuple(item - center for item, center in zip(first, middle))
    right = tuple(item - center for item, center in zip(third, middle))
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0 or right_norm == 0:
        raise GeometryError("angle vectors must have non-zero length")
    cosine = sum(x * y for x, y in zip(left, right)) / (left_norm * right_norm)
    radians = math.acos(max(-1.0, min(1.0, cosine)))
    normalized_unit = str(unit).lower()
    if normalized_unit not in {"degrees", "radians"}:
        raise GeometryError("unit must be degrees or radians")
    return {"angle": math.degrees(radians) if normalized_unit == "degrees" else radians, "unit": normalized_unit, "deterministic": True}


def polygon_area(values: Any) -> dict[str, Any]:
    parsed = points(values, "points", minimum=3)
    if len(parsed[0]) != 2:
        raise GeometryError("area currently accepts two-dimensional points")
    signed = sum(parsed[index][0] * parsed[(index + 1) % len(parsed)][1] - parsed[(index + 1) % len(parsed)][0] * parsed[index][1] for index in range(len(parsed))) / 2
    return {"area": abs(signed), "signed_area": signed, "unit": "square_units", "deterministic": True}


def contour(values: Any, closed: bool = True) -> dict[str, Any]:
    parsed = points(values, "points", minimum=2)
    perimeter = sum(math.dist(parsed[index], parsed[index + 1]) for index in range(len(parsed) - 1))
    if closed:
        perimeter += math.dist(parsed[-1], parsed[0])
    output = {"points": [list(item) for item in parsed], "perimeter": perimeter, "closed": bool(closed), "deterministic": True}
    if len(parsed) >= 3 and len(parsed[0]) == 2:
        output["area"] = polygon_area(values)["area"]
    return output


def _matrix(value: Any, rows: int, columns: int, field: str) -> list[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != rows or any(not isinstance(row, (list, tuple)) or len(row) != columns for row in value):
        raise GeometryError(f"{field} must be a {rows}x{columns} matrix")
    return [[_number(item, f"{field}[{row}][{column}]") for column, item in enumerate(values)] for row, values in enumerate(value)]


def _solve_linear(matrix: list[list[float]], values: list[float]) -> list[float]:
    size = len(values)
    augmented = [list(row) + [values[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise GeometryError("matrix is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [item / divisor for item in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [left - factor * right for left, right in zip(augmented[row], augmented[column])]
    return [augmented[index][-1] for index in range(size)]


def homography(source: Any, destination: Any) -> dict[str, Any]:
    source_points = points(source, "source", minimum=4)
    destination_points = points(destination, "destination", minimum=4)
    if len(source_points) != len(destination_points) or len(source_points) < 4:
        raise GeometryError("source and destination need the same four or more points")
    if len(source_points[0]) != 2 or len(destination_points[0]) != 2:
        raise GeometryError("homography accepts two-dimensional points")
    equations: list[list[float]] = []
    targets: list[float] = []
    for (x, y), (u, v) in zip(source_points, destination_points):
        equations.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        targets.append(u)
        equations.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        targets.append(v)
    coefficients = _solve_linear(equations[:8], targets[:8]) if len(equations) == 8 else _least_squares(equations, targets)
    matrix = [coefficients[:3], coefficients[3:6], [coefficients[6], coefficients[7], 1.0]]
    return {"matrix": matrix, "source_points": [list(item) for item in source_points], "destination_points": [list(item) for item in destination_points], "deterministic": True}


def _least_squares(matrix: list[list[float]], values: list[float]) -> list[float]:
    transposed = list(zip(*matrix))
    normal = [[sum(row[i] * row[j] for row in matrix) for j in range(8)] for i in range(8)]
    target = [sum(transposed[i][row] * values[row] for row in range(len(values))) for i in range(8)]
    return _solve_linear(normal, target)


def transform_points(values: Any, matrix: Any) -> dict[str, Any]:
    parsed = points(values, "points", minimum=1)
    if any(len(item) != 2 for item in parsed):
        raise GeometryError("perspective transform accepts two-dimensional points")
    transform = _matrix(matrix, 3, 3, "matrix")
    transformed = []
    for x, y in parsed:
        denominator = transform[2][0] * x + transform[2][1] * y + transform[2][2]
        if abs(denominator) < 1e-12:
            raise GeometryError("perspective transform maps a point to infinity")
        transformed.append([(transform[0][0] * x + transform[0][1] * y + transform[0][2]) / denominator, (transform[1][0] * x + transform[1][1] * y + transform[1][2]) / denominator])
    return {"points": transformed, "matrix": transform, "deterministic": True}


def calibrate_camera(image_size: Any, object_points: Any = None, image_points: Any = None) -> dict[str, Any]:
    if not isinstance(image_size, (list, tuple)) or len(image_size) != 2:
        raise GeometryError("image_size must be [width, height]")
    width = int(_number(image_size[0], "image_size[0]"))
    height = int(_number(image_size[1], "image_size[1]"))
    if width <= 0 or height <= 0:
        raise GeometryError("image_size must be positive")
    if object_points is not None or image_points is not None:
        object_values = points(object_points, "object_points", minimum=4)
        image_values = points(image_points, "image_points", minimum=4)
        if len(object_values) != len(image_values):
            raise GeometryError("object_points and image_points must have equal lengths")
    focal = float(max(width, height))
    return {"camera_matrix": [[focal, 0.0, width / 2], [0.0, focal, height / 2], [0.0, 0.0, 1.0]], "distortion": [0.0, 0.0, 0.0, 0.0, 0.0], "image_size": [width, height], "estimated": True, "deterministic": True}


def solve_pnp(object_points: Any, image_points: Any, camera_matrix: Any, distortion: Any = None) -> dict[str, Any]:
    objects = points(object_points, "object_points", minimum=4)
    images = points(image_points, "image_points", minimum=4)
    if len(objects) != len(images) or len(objects[0]) != 3 or len(images[0]) != 2:
        raise GeometryError("solve_pnp needs equal 3D object and 2D image point sets")
    camera = _matrix(camera_matrix, 3, 3, "camera_matrix")
    if distortion is None:
        coefficients = [0.0, 0.0, 0.0, 0.0, 0.0]
    else:
        if not isinstance(distortion, (list, tuple)) or len(distortion) not in {4, 5, 8, 12, 14}:
            raise GeometryError("distortion must contain 4, 5, 8, 12, or 14 coefficients")
        coefficients = [_number(value, f"distortion[{index}]") for index, value in enumerate(distortion)]
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise GeometryDependencyError("solve_pnp requires OpenCV; install the vision-operators pack with dependencies") from exc

    object_array = np.asarray(objects, dtype=np.float64)
    image_array = np.asarray(images, dtype=np.float64)
    camera_array = np.asarray(camera, dtype=np.float64)
    distortion_array = np.asarray(coefficients, dtype=np.float64)
    try:
        solved, rotation, translation = cv2.solvePnP(
            object_array,
            image_array,
            camera_array,
            distortion_array,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not solved:
            raise GeometryError("OpenCV could not solve the supplied camera pose")
        rotation_matrix, _ = cv2.Rodrigues(rotation)
        projected, _ = cv2.projectPoints(object_array, rotation, translation, camera_array, distortion_array)
    except GeometryError:
        raise
    except cv2.error as exc:
        raise GeometryError(f"OpenCV could not solve the supplied camera pose: {exc}") from exc
    residuals = projected.reshape(-1, 2) - image_array
    reprojection_error = float(np.sqrt(np.mean(np.sum(residuals * residuals, axis=1))))
    return {
        "rotation_vector": rotation.reshape(-1).astype(float).tolist(),
        "translation_vector": translation.reshape(-1).astype(float).tolist(),
        "rotation_matrix": rotation_matrix.astype(float).tolist(),
        "reprojection_error": reprojection_error,
        "point_count": len(objects),
        "deterministic": True,
    }


def match_features(_image_a: Any, _image_b: Any, **options: Any) -> dict[str, Any]:
    first = _image_path(_image_a, "image_a")
    second = _image_path(_image_b, "image_b")
    max_features = options.get("max_features", 1000)
    if isinstance(max_features, bool) or not isinstance(max_features, int) or not 32 <= max_features <= 10_000:
        raise GeometryError("max_features must be an integer between 32 and 10000")
    ratio = _number(options.get("ratio", 0.75), "ratio")
    if not 0.1 <= ratio <= 1.0:
        raise GeometryError("ratio must be between 0.1 and 1.0")
    try:
        import cv2
    except ImportError as exc:
        raise GeometryDependencyError("feature matching requires OpenCV; install the vision-operators pack with dependencies") from exc

    image_a = cv2.imread(str(first), cv2.IMREAD_GRAYSCALE)
    image_b = cv2.imread(str(second), cv2.IMREAD_GRAYSCALE)
    if image_a is None or image_b is None:
        raise GeometryError("feature matching inputs must be readable images")
    cv2.setRNGSeed(0)
    detector = cv2.ORB_create(nfeatures=max_features)
    keypoints_a, descriptors_a = detector.detectAndCompute(image_a, None)
    keypoints_b, descriptors_b = detector.detectAndCompute(image_b, None)
    if descriptors_a is None or descriptors_b is None:
        return {
            "algorithm": "ORB",
            "keypoints_a": len(keypoints_a),
            "keypoints_b": len(keypoints_b),
            "match_count": 0,
            "matches": [],
            "deterministic": True,
        }
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    candidates = matcher.knnMatch(descriptors_a, descriptors_b, k=2)
    accepted = []
    for pair in candidates:
        if len(pair) != 2:
            continue
        best, runner_up = pair
        if best.distance <= ratio * runner_up.distance:
            accepted.append(best)
    accepted.sort(key=lambda item: (float(item.distance), int(item.queryIdx), int(item.trainIdx)))
    matches = [
        {
            "a": [float(value) for value in keypoints_a[item.queryIdx].pt],
            "b": [float(value) for value in keypoints_b[item.trainIdx].pt],
            "distance": float(item.distance),
        }
        for item in accepted[:500]
    ]
    return {
        "algorithm": "ORB",
        "keypoints_a": len(keypoints_a),
        "keypoints_b": len(keypoints_b),
        "match_count": len(accepted),
        "matches": matches,
        "ratio": ratio,
        "deterministic": True,
    }


def _image_path(value: Any, field: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise GeometryError(f"{field} must be a local image path")
    path = Path(value).expanduser()
    if not path.is_file():
        raise GeometryError(f"{field} file does not exist: {path}")
    if path.stat().st_size > 512 * 1024 * 1024:
        raise GeometryError(f"{field} exceeds the 512 MiB input limit")
    return path
