"""
Script to run Structure-from-Motion with Rig Constraints derived from Blender.
Input path should contain subdirectories (e.g. table2_low, table2_mid, table2_top),
each containing a 'cameras.json' file and subfolders for each camera (Camera0, Camera1...).
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pycolmap

def load_blender_cameras(json_path: Path) -> Dict[str, np.ndarray]:
    """
    Loads camera poses from Blender export.
    Returns dict: camera_name -> 4x4 matrix_world
    """
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    cameras = {}
    for name, cam_data in data.items():
        mat = np.array(cam_data["matrix_world"])
        cameras[name] = mat
    return cameras

def blender_to_colmap_matrix():
    """
    Returns the transformation matrix to convert from Blender Camera 
    coordinate system (Right, Up, Back) to COLMAP Camera coordinate system (Right, Down, Forward).
    Blender: X Right, Y Up, -Z View
    COLMAP: X Right, Y Down, +Z View
    
    Transformation: Flip Y and Z axes.
    """
    return np.diag([1, -1, -1, 1])

def compute_rig_config(
    folder_path: Path, 
    blender_cameras: Dict[str, np.ndarray],
    ref_camera_name: str = "Camera0"
) -> Optional[pycolmap.RigConfig]:
    """
    Creates a RigConfig for the given folder based on Blender poses.
    """
    if ref_camera_name not in blender_cameras:
        if not blender_cameras:
            return None
        ref_camera_name = list(blender_cameras.keys())[0]
        
    logging.info(f"Creating RigConfig for {folder_path.name} using ref {ref_camera_name}")
    
    B2C = blender_to_colmap_matrix()
    
    M_ref_w = blender_cameras[ref_camera_name] @ B2C
    
    rig_cameras = []
    
    # Reference sensor MUST be added first — pycolmap enforces this.
    # Sort so ref comes first, then the rest alphabetically.
    sorted_cam_names = sorted(
        blender_cameras.keys(),
        key=lambda n: (n != ref_camera_name, n)
    )
    
    for cam_name in sorted_cam_names:
        prefix = f"{folder_path.name}/{cam_name}/"
        
        if cam_name == ref_camera_name:
            cam_from_rig = None  # Identity — this is the rig origin
        else:
            M_cam_w = blender_cameras[cam_name] @ B2C
            T_c_r = np.linalg.inv(M_cam_w) @ M_ref_w
            
            R = T_c_r[:3, :3]
            t = T_c_r[:3, 3]
            
            cam_from_rig = pycolmap.Rigid3d(pycolmap.Rotation3d(R), t)
            
            distance = np.linalg.norm(t)
            cos_angle = np.clip((np.trace(R) - 1) / 2, -1.0, 1.0)
            angle_deg = np.rad2deg(np.arccos(cos_angle))
            logging.info(f"  {cam_name} → {ref_camera_name}: distance={distance:.3f}m, rotation={angle_deg:.1f}°")
            
        rig_cameras.append(
            pycolmap.RigConfigCamera(
                ref_sensor=(cam_name == ref_camera_name),
                image_prefix=prefix,
                cam_from_rig=cam_from_rig
            )
        )
        
    return pycolmap.RigConfig(cameras=rig_cameras)

def run(args):
    input_path = args.input_path
    output_path = args.output_path
    matching = args.matching
    
    database_path = output_path / "database.db"
    output_path.mkdir(exist_ok=True, parents=True)
    
    if database_path.exists():
        database_path.unlink()
        
    rig_configs = []
    
    subdirs = [p for p in input_path.iterdir() if p.is_dir()]
    logging.info(f"Found {len(subdirs)} subdirectories in {input_path}")
    
    for subdir in subdirs:
        json_path = subdir / "cameras.json"
        if not json_path.exists():
            logging.warning(f"No cameras.json found in {subdir}, skipping rig config for this folder.")
            continue
            
        blender_cameras = load_blender_cameras(json_path)
        rig_config = compute_rig_config(subdir, blender_cameras)
        if rig_config:
            rig_configs.append(rig_config)
            
    if not rig_configs:
        logging.warning("No valid rig configurations found.")
        
    logging.info("Extracting features...")
    pycolmap.set_random_seed(0)
    
    ### This was here for triangle-splatting2
    #reader_options = pycolmap.ImageReaderOptions()
    #reader_options.camera_model = "PINHOLE"

    pycolmap.extract_features(
        database_path, 
        input_path, 
        camera_mode=pycolmap.CameraMode.PER_FOLDER
        #reader_options=reader_options
    )
    
    if rig_configs:
        logging.info(f"Applying {len(rig_configs)} rig configurations...")
        with pycolmap.Database.open(database_path) as db:
            pycolmap.apply_rig_config(rig_configs, db)


    # Shared across all strategies
    def base_matching_options(use_gpu=False):
        opts = pycolmap.FeatureMatchingOptions()
        opts.rig_verification = True
        opts.skip_image_pairs_in_same_frame = True
        opts.use_gpu = use_gpu
        opts.guided_matching = True          # uses known rig geometry to guide SIFT — big help for interiors
        opts.sift.max_ratio = 0.75           # tighter than default 0.8 — reduces false matches on repetitive textures
        opts.sift.cross_check = True         # already default, but explicit is good
        return opts


    def base_verification_options():
        opts = pycolmap.TwoViewGeometryOptions()
        opts.min_num_inliers = 20            # default 15 is too loose for featureless interiors
        opts.min_E_F_inlier_ratio = 0.95     # already default, keep it
        opts.ransac.max_error = 3.0          # tighter reprojection — default 4.0 lets sloppy pairs through
        opts.ransac.min_inlier_ratio = 0.3   # slightly above default 0.25
        return opts


    if matching == "vocabtree":
        logging.info("Matching features (VocabTree)...")

        pairing = pycolmap.VocabTreePairingOptions()
        pairing.num_images = 20              # candidates per query; 100 default is wasteful and noisy for interiors
        pairing.num_nearest_neighbors = 5    # top-5 retrieved images to verify; default is fine
        pairing.num_checks = 64              # FAISS probe depth; increase to 128 if recall is poor
        pairing.num_images_after_verification = 10  # keep top-10 after geometric verification

        pycolmap.match_vocabtree(
            database_path,
            matching_options=base_matching_options(),
            pairing_options=pairing,
            verification_options=base_verification_options(),
        )

    elif matching == "sequential":
        logging.info("Matching features (Sequential)...")

        pairing = pycolmap.SequentialPairingOptions()
        pairing.overlap = 7                  # match each rig to 7 temporal neighbors; tune to your fps/speed
        pairing.quadratic_overlap = True     # also matches at 1,4,9,16... frames back — better for varying speed
        pairing.expand_rig_images = True     # already default True — ensures all rig perspectives get matched
        pairing.loop_detection = True        # enables built-in loop closure via vocab tree
        pairing.loop_detection_period = 15   # check for loops every 1 frames
        pairing.loop_detection_num_images = 8   # retrieve top-8 candidates; keep low for repetitive interiors
        pairing.loop_detection_num_nearest_neighbors = 1
        pairing.loop_detection_num_images_after_verification = 5

        pycolmap.match_sequential(
            database_path,
            matching_options=base_matching_options(),
            pairing_options=pairing,
            verification_options=base_verification_options(),
        )

    elif matching == "exhaustive":
        logging.info("Matching features (Exhaustive)...")
        pycolmap.match_exhaustive(
            database_path,
            matching_options=base_matching_options(use_gpu=True),
            verification_options=base_verification_options(),
        )
    rec_path = output_path / "sparse"
    rec_path.mkdir(exist_ok=True, parents=True)
    
    logging.info("Starting incremental mapping...")
    
    maps = pycolmap.incremental_mapping(
        database_path, 
        input_path, 
        rec_path
    )
    
    for idx, rec in maps.items():
        logging.info(f"Reconstruction #{idx}: {rec.summary()}")
        
    logging.info("Done.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_path", type=Path, required=True, help="Parent folder containing subdirs with cameras.json")
    parser.add_argument("--output_path", type=Path, required=True, help="Output folder for database and sparse reconstruction")
    parser.add_argument("--matching", type=str, default="vocabtree", required=False, help="Matching method (vocabtree (default), sequential or exhaustive)")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format="[COLMAP] %(message)s")
    run(args)