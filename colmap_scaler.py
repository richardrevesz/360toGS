"""
Scale a COLMAP sparse reconstruction in TXT format.
Edits images.txt (tvec) and points3D.txt (xyz) in place.
Usage: python colmap_scaler.py --input <sparse_txt_folder> --output <output_folder> --scale 0.001
"""

import argparse
import os
import shutil
from pathlib import Path

def scale_images(input_path, output_path, scale):
    in_file  = input_path / "images.txt"
    out_file = output_path / "images.txt"

    with open(in_file, 'r') as f:
        lines = f.readlines()

    out_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Comment or empty line — pass through unchanged
        if line.startswith('#') or line.strip() == '':
            out_lines.append(line)
            i += 1
            continue

        # Image line: IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME
        parts = line.split()
        if len(parts) >= 9:
            image_id  = parts[0]
            qw, qx, qy, qz = parts[1], parts[2], parts[3], parts[4]
            tx = float(parts[5]) * scale
            ty = float(parts[6]) * scale
            tz = float(parts[7]) * scale
            camera_id = parts[8]
            name      = parts[9] if len(parts) > 9 else ''
            new_line  = f"{image_id} {qw} {qx} {qy} {qz} {tx:.10f} {ty:.10f} {tz:.10f} {camera_id} {name}\n"
            out_lines.append(new_line)
            i += 1
            # Next line is the points2D line — pass through unchanged
            if i < len(lines):
                out_lines.append(lines[i])
                i += 1
        else:
            out_lines.append(line)
            i += 1

    with open(out_file, 'w') as f:
        f.writelines(out_lines)

    print(f"Wrote scaled images.txt ({sum(1 for l in out_lines if l and not l.startswith('#'))} lines)")


def scale_points3d(input_path, output_path, scale):
    in_file  = input_path / "points3D.txt"
    out_file = output_path / "points3D.txt"

    with open(in_file, 'r') as f:
        lines = f.readlines()

    out_lines = []
    for line in lines:
        if line.startswith('#') or line.strip() == '':
            out_lines.append(line)
            continue

        # POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]
        parts = line.split()
        point_id = parts[0]
        x = float(parts[1]) * scale
        y = float(parts[2]) * scale
        z = float(parts[3]) * scale
        rest = ' '.join(parts[4:])
        out_lines.append(f"{point_id} {x:.10f} {y:.10f} {z:.10f} {rest}\n")

    with open(out_file, 'w') as f:
        f.writelines(out_lines)

    print(f"Wrote scaled points3D.txt ({len(out_lines)} lines)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  type=Path, required=True, help='Input folder with images.txt, cameras.txt, points3D.txt')
    parser.add_argument('--output', type=Path, required=True, help='Output folder')
    parser.add_argument('--scale',  type=float, default=0.001, help='Scale factor (default: 0.001)')
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    # cameras.txt does not need scaling — intrinsics are in pixels
    shutil.copy(args.input / "cameras.txt", args.output / "cameras.txt")
    print("Copied cameras.txt unchanged (intrinsics are in pixels, no scaling needed)")

    scale_images(args.input, args.output, args.scale)
    scale_points3d(args.input, args.output, args.scale)

    print(f"\nDone. Scaled by {args.scale}. Output in: {args.output}")

if __name__ == "__main__":
    main()
