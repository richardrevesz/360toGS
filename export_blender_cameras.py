import bpy
import json
import os
import mathutils

def export_cameras():
    """
    Exports all camera objects in the current scene to a JSON file.
    The JSON will clearly map camera names to their World Matrices.
    """
    
    # Path to save the json. Defaults to the same folder as the blend file.
    # If blend file is not saved, saves to C:/tmp or similar (user might need to adjust).
    blend_path = bpy.data.filepath
    if blend_path:
        base_dir = os.path.dirname(blend_path)
    else:
        base_dir = "C:/tmp" # Fallback
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
            
    output_path = os.path.join(base_dir, "cameras.json")
    
    cameras_data = {}
    
    # Iterate through all objects
    for obj in bpy.context.scene.objects:
        if obj.type == 'CAMERA':
            # Get the matrix_world
            # This is the transform from Local-Camera space to World space.
            mw = obj.matrix_world
            
            # Convert to list of lists for JSON
            mat_list = [
                [mw[0][0], mw[0][1], mw[0][2], mw[0][3]],
                [mw[1][0], mw[1][1], mw[1][2], mw[1][3]],
                [mw[2][0], mw[2][1], mw[2][2], mw[2][3]],
                [mw[3][0], mw[3][1], mw[3][2], mw[3][3]]
            ]
            
            # We use the object name as the key. 
            # The User mentioned folders like "Camera0", "Camera1".
            # Hopefully the Blender objects are named "Camera0", "Camera1" etc.
            cameras_data[obj.name] = {
                "matrix_world": mat_list,
                "location": [mw[0][3], mw[1][3], mw[2][3]],
                # Lens info could be useful
                "lens": obj.data.lens,
                "sensor_width": obj.data.sensor_width,
                "sensor_height": obj.data.sensor_height
            }
            
    with open(output_path, 'w') as f:
        json.dump(cameras_data, f, indent=4)
        
    print(f"Exported {len(cameras_data)} cameras to {output_path}")
    
    # Show a popup in Blender
    def draw(self, context):
        self.layout.label(text=f"Exported to {output_path}")
    bpy.context.window_manager.popup_menu(draw, title="Export Successful", icon='INFO')

if __name__ == "__main__":
    export_cameras()
