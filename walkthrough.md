# Walkthrough: Custom Rig Reconstruction from Blender

This guide explains how to use the new scripts to export camera poses from Blender and use them to constrain your COLMAP reconstruction.

## 1. Export Cameras from Blender

You need to export the camera poses for **each** of your scenes (`table2_low`, `table2_mid`, `table2_top`).

1.  Open your Blender project for one of the setups (e.g., `table2_low`).
2.  Go to the Scripting tab.
3.  Open/Paste the `export_blender_cameras.py` script.
4.  Run the script.
    -   It will create a `cameras.json` file in the same directory as your `.blend` file (or `C:/tmp` if unsaved).
5.  **Move** the generated `cameras.json` into the corresponding image folder (e.g., inside `path/to/table2_low`).
6.  Repeat for `table2_mid` and `table2_top` (ensure you have the unique `cameras.json` for each).

Your folder structure should look like this:
```
path/to/dataset/
├── table2_low/
│   ├── cameras.json  <-- Exported from Blender
│   ├── Camera0/
│   │   └── image.png
│   └── Camera1/
│       └── image.png
├── table2_mid/
│   ├── cameras.json
│   └── ...
└── table2_top/
    ├── cameras.json
    └── ...

> [!IMPORTANT]
> **Naming Rule**: The Camera Object names in Blender (e.g., "Camera0", "Camera3") **MUST** exactly match the subfolder names where you put your images. If your folder is named `Camera3`, your Blender camera must be named `Camera3`.
```

## 2. Run Reconstruction

Run the new Python script `rig_sfm_custom.py`. Point the `input_path` to the **parent** directory containing your 3 folders.

```bash
python examples/rig_sfm_custom.py --input_path "path/to/dataset" --output_path "path/to/output"
```

### What Happens
1.  **Scanning**: The script finds `table2_low`, `table2_mid`, `table2_top`.
2.  **Rig Config**: For each folder, it reads `cameras.json` and creates a unique Rig Configuration.
    -   It acts as if you have 3 different rigs.
    -   The relative poses of cameras *within* each rig are fixed based on Blender values.
3.  **Feature Extraction**: It extracts features for all images.
4.  **Matching**: It exhaustively matches features between all images (linking low, mid, and top).
5.  **Reconstruction**: It runs incremental mapping, using the Rig Constraints to stabilize the geometry.

## Troubleshooting

-   **"No cameras.json found"**: Ensure you copied the JSON file to the correct folder.
-   **Coordinate System**: The script automatically converts Blender coordinates (Z-Back, Y-Up) to COLMAP (Z-Forward, Y-Down). If your cameras look "backward" in the reconstruction, check if you have valid camera objects in Blender.
