"""Export final structural meshes in assembly coordinates, millimetres.
Run with Blender --background --python tools/export_parts.py.
The sole editable source is the .blend file at this package's root.
"""
from pathlib import Path
import bpy, json, struct

PARTS = ['shell_A', 'shell_B', 'one_piece_core', 'camera_cover_cradle', 'fixed_base', 'base_top_cover', 'pitch_pinion_40T', 'pitch_servo_clamp_strap', 'pitch_servo_clamp_pads', 'yaw_bearing_cap', 'yaw_spur_pinion_16T', 'yaw_shaft_retainer', 'yaw_service_cover', 'charge_lead_clamp', 'speaker_top_bridge']

def export_parts(root):
    dest = root / 'parts'
    dest.mkdir(exist_ok=True)
    ctrl = bpy.data.objects['CONTROLS_Dolphin']
    ctrl['pitch_servo_deg'] = 90.0
    ctrl['body_yaw_deg'] = 0.0
    ctrl.update_tag()
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    result = []
    for name in PARTS:
        obj = bpy.data.objects[name]
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        points = [obj.matrix_world @ v.co for v in mesh.vertices]
        target = dest / (name + '.stl')
        with target.open('wb') as stream:
            stream.write(b'Structural concept; assembly coordinates; unit mm'.ljust(80, b'\0'))
            stream.write(struct.pack('<I', len(mesh.loop_triangles)))
            for tri in mesh.loop_triangles:
                vertices = [points[i] for i in tri.vertices]
                normal = (vertices[1]-vertices[0]).cross(vertices[2]-vertices[0]).normalized()
                stream.write(struct.pack('<12fH', *normal, *vertices[0], *vertices[1], *vertices[2], 0))
        bounds = [[min(v[i] for v in points) for i in range(3)],
                  [max(v[i] for v in points) for i in range(3)]]
        result.append(dict(object=name, file=target.name, bounds_mm=bounds,
                           triangles=len(mesh.loop_triangles),
                           status='structural layout prototype; hardware and print fit unqualified'))
        evaluated.to_mesh_clear()
    (dest/'index.json').write_text(json.dumps(dict(units='mm', coordinates='neutral assembly', parts=result), indent=2))
    return result

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    files = list(root.glob('*.blend'))
    assert len(files) == 1, 'Expected exactly one editable Blender source.'
    bpy.ops.wm.open_mainfile(filepath=str(files[0]))
    export_parts(root)
    print('STRUCTURAL_EXPORT_COMPLETE')
