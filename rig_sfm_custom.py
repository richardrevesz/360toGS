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

def blender_to_colmap_matrix(width=None, height=None):
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
        # Fallback to first available if default ref not found
        if not blender_cameras:
            return None
        ref_camera_name = list(blender_cameras.keys())[0]
        
    logging.info(f"Creating RigConfig for {folder_path.name} using ref {ref_camera_name}")
    
    # 1. Get Reference Camera World Matrix in COLMAP coords
    # M_ref_world = M_ref_blender * B2C
    # Wait, M_blender is Local -> World.
    # P_world = M_blender * P_local_blender
    # We want P_local_colmap.
    # P_local_colmap = B2C * P_local_blender => P_local_blender = inv(B2C) * P_local_colmap
    # P_world_colmap = M_blender * inv(B2C) * P_local_colmap
    # But P_world_colmap is same as P_world (World coords are same).
    # So M_colmap = M_blender * inv(B2C).
    # Since B2C is diag(1, -1, -1), inv(B2C) = B2C.
    
    B2C = blender_to_colmap_matrix()
    
    M_ref_w = blender_cameras[ref_camera_name] @ B2C
    M_ref_w_inv = np.linalg.inv(M_ref_w)
    
    rig_cameras = []
    
    # Check which cameras actually exist in the folder (as subfolders)
    # The usage assumes image structure: colmap/rig/CameraName/frame#.png
    # But we need to match the blender name.
    
    sorted_cam_names = sorted(blender_cameras.keys())
    
    for cam_name in sorted_cam_names:
        # Construct prefix. 
        # COLMAP ImageReader with PER_FOLDER mode will use the relative path 
        # from the root image_path. 
        # The root image_path passed to extract_features will likely be the parent containing table2_low etc.
        # So the image name in DB will be "table2_low/Camera0/frame.png".
        # The prefix should match this.
        
        prefix = f"{folder_path.name}/{cam_name}/"
        
        # Calculate cam_from_rig
        # Rig is defined as the Reference Camera Frame.
        if cam_name == ref_camera_name:
            cam_from_rig = None # Identity
        else:
            # T_cam_from_ref = T_cam_from_world * T_world_from_ref
            # T_cam_from_ref = inv(M_cam_w) * M_ref_w
            
            M_cam_w = blender_cameras[cam_name] @ B2C
            M_cam_w_inv = np.linalg.inv(M_cam_w)
            
            # The definition of cam_from_rig in pycolmap is "Transform FROM rig frame TO camera frame".
            # If Rig Frame = Ref Frame.
            # We need T_c_r = inv(M_c) * M_r.
            # Using 4x4 matrices.
            
            T_c_r = M_cam_w_inv @ M_ref_w
            
            # Extract Rotation and Translation
            R = T_c_r[:3, :3]
            t = T_c_r[:3, 3]
            
            cam_from_rig = pycolmap.Rigid3d(pycolmap.Rotation3d(R), t)
            
            # Debug: Print rig geometry to verify correctness
            distance = np.linalg.norm(t)
            # Clamp to avoid numerical issues when trace is slightly outside [-1, 1]
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
    output_path = args.output_path
    image_dir = output_path / "images" # COLMAP needs images in one place? No, can extract from source.
    # Actually, we can just point COLMAP to the source folder if we don't need to copy.
    # But usually it's safer to not modify source.
    # However, copying is slow.
    # Let's use the input path directly as image_path.
    
    input_path = args.input_path
    
    database_path = output_path / "database.db"
    output_path.mkdir(exist_ok=True, parents=True)
    
    if database_path.exists():
        database_path.unlink()
        
    rig_configs = []
    
    # Scan for subdirectories
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
        
    # Extract features
    # usage: extract_features(database, image_path, ...)
    # detailed: pycolmap.extract_features(database_path, image_path)
    
    logging.info("Extracting features...")
    pycolmap.set_random_seed(0)
    
    # We assume standard feature extraction is sufficient.
    pycolmap.extract_features(
        database_path, 
        input_path, 
        camera_mode=pycolmap.CameraMode.PER_FOLDER
    )
    
    # Apply Rig Configs
    if rig_configs:
        logging.info(f"Applying {len(rig_configs)} rig configurations...")
        with pycolmap.Database.open(database_path) as db:
            pycolmap.apply_rig_config(rig_configs, db)
    
    # Matching
    logging.info("Matching features (VocabTree)...")
    # Configure matching to leverage rig geometry for speed
    matching_options = pycolmap.FeatureMatchingOptions()
    matching_options.rig_verification = True  # Use rig constraints for verification
    matching_options.skip_image_pairs_in_same_frame = True  # Skip within-rig matching
    pycolmap.match_vocabtree(database_path, matching_options=matching_options)
    
    # Reconstruction
    rec_path = output_path / "sparse"
    rec_path.mkdir(exist_ok=True, parents=True)
    
    logging.info("Starting incremental mapping...")
    
    # Default RigConfig assumes fixed relative poses but allows rig to move.
    
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
    parser.add_argument("--input_path", type=Path, required=True, help="Parent folder containing table2_low, etc.")
    parser.add_argument("--output_path", type=Path, required=True, help="Output folder")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    run(args)
