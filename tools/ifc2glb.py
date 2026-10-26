"""Convert an IFC file to GLB with IfcOpenShell (node names = IFC GlobalId, world coordinates, Y up).

Usage: uv run --with ifcopenshell python -I tools/ifc2glb.py <in.ifc> <out.glb>
"""
import multiprocessing
import sys

import ifcopenshell
import ifcopenshell.geom


def convert(src, out):
    f = ifcopenshell.open(src)
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    s.set("weld-vertices", True)
    s.set("use-element-guids", True)  # IfcOpenShell 0.9: one settings object for geometry and serializer
    ser = ifcopenshell.geom.serializers.glb(out, s)
    ser.setFile(f)
    ser.setUnitNameAndMagnitude("METER", 1.0)
    ser.writeHeader()
    it = ifcopenshell.geom.iterator(s, f, multiprocessing.cpu_count(), exclude=("IfcSpace", "IfcOpeningElement"))
    n = 0
    if it.initialize():
        while True:
            ser.write(it.get())
            n += 1
            if not it.next():
                break
    ser.finalize()
    print(f"{out}: {n} elementos")


if __name__ == "__main__":
    convert(*sys.argv[1:])
