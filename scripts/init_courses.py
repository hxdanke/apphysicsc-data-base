"""Create the three courses added alongside AP Physics C: Mechanics.

Writes each course's taxonomy (units and topics taken from the College Board
course framework) and a bank holding one sample question, plus the shared
placeholder image an empty image block renders as.

Idempotent: it only writes a file that is missing, so re-running never clobbers
work.  Pass ``--force`` to overwrite the sample banks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf  # noqa: E402

from server import courses as courses_mod  # noqa: E402

ROOT = courses_mod.ROOT

# --------------------------------------------------------------------------------------
# taxonomies
# --------------------------------------------------------------------------------------

TAXONOMIES = {
    "apc-em": {
        "course": "AP Physics C: Electricity and Magnetism",
        "units": [
            {"id": 1, "title": "Electrostatics", "topics": [
                {"id": "1.1", "title": "Charge Distributions"},
                {"id": "1.2", "title": "Electric Fields"},
                {"id": "1.3", "title": "Electric Flux and Gauss's Law"},
                {"id": "1.4", "title": "Electric Potential"},
            ]},
            {"id": 2, "title": "Conductors, Capacitors, Dielectrics", "topics": [
                {"id": "2.1", "title": "Electrostatics with Conductors"},
                {"id": "2.2", "title": "Capacitors"},
                {"id": "2.3", "title": "Dielectrics"},
            ]},
            {"id": 3, "title": "Electric Circuits", "topics": [
                {"id": "3.1", "title": "Current, Resistance, and EMF"},
                {"id": "3.2", "title": "Resistive Circuits"},
                {"id": "3.3", "title": "RC Circuits"},
            ]},
            {"id": 4, "title": "Magnetic Fields", "topics": [
                {"id": "4.1", "title": "Magnetic Fields and Forces"},
                {"id": "4.2", "title": "Sources of Magnetic Fields"},
                {"id": "4.3", "title": "Magnetic Flux"},
            ]},
            {"id": 5, "title": "Electromagnetic Induction", "topics": [
                {"id": "5.1", "title": "Faraday's Law and Lenz's Law"},
                {"id": "5.2", "title": "Inductance"},
                {"id": "5.3", "title": "LC and RLC Circuits"},
                {"id": "5.4", "title": "Maxwell's Equations"},
            ]},
        ],
    },
    "ap1": {
        "course": "AP Physics 1",
        "units": [
            {"id": 1, "title": "Kinematics", "topics": [
                {"id": "1.1", "title": "Position, Velocity, and Acceleration"},
                {"id": "1.2", "title": "Representations of Motion"},
                {"id": "1.3", "title": "Motion in Two Dimensions"},
            ]},
            {"id": 2, "title": "Force and Translational Dynamics", "topics": [
                {"id": "2.1", "title": "Systems and Center of Mass"},
                {"id": "2.2", "title": "Forces and Free-Body Diagrams"},
                {"id": "2.3", "title": "Newton's Third Law"},
                {"id": "2.4", "title": "Newton's First Law"},
                {"id": "2.5", "title": "Newton's Second Law"},
                {"id": "2.6", "title": "Gravitational Force"},
                {"id": "2.7", "title": "Friction"},
                {"id": "2.8", "title": "Spring Forces"},
                {"id": "2.9", "title": "Resistive Forces"},
                {"id": "2.10", "title": "Circular Motion"},
            ]},
            {"id": 3, "title": "Work, Energy, and Power", "topics": [
                {"id": "3.1", "title": "Translational Kinetic Energy"},
                {"id": "3.2", "title": "Work"},
                {"id": "3.3", "title": "Potential Energy"},
                {"id": "3.4", "title": "Conservation of Energy"},
                {"id": "3.5", "title": "Power"},
            ]},
            {"id": 4, "title": "Linear Momentum", "topics": [
                {"id": "4.1", "title": "Linear Momentum"},
                {"id": "4.2", "title": "Change in Momentum and Impulse"},
                {"id": "4.3", "title": "Conservation of Linear Momentum"},
                {"id": "4.4", "title": "Elastic and Inelastic Collisions"},
            ]},
            {"id": 5, "title": "Torque and Rotational Dynamics", "topics": [
                {"id": "5.1", "title": "Rotational Kinematics"},
                {"id": "5.2", "title": "Connecting Linear and Rotational Motion"},
                {"id": "5.3", "title": "Torque"},
                {"id": "5.4", "title": "Rotational Inertia"},
                {"id": "5.5", "title": "Rotational Equilibrium"},
                {"id": "5.6", "title": "Newton's Second Law in Rotational Form"},
            ]},
            {"id": 6, "title": "Energy and Momentum of Rotating Systems", "topics": [
                {"id": "6.1", "title": "Rotational Kinetic Energy"},
                {"id": "6.2", "title": "Torque and Work"},
                {"id": "6.3", "title": "Angular Momentum"},
                {"id": "6.4", "title": "Conservation of Angular Momentum"},
                {"id": "6.5", "title": "Rolling"},
            ]},
            {"id": 7, "title": "Oscillations", "topics": [
                {"id": "7.1", "title": "Defining Simple Harmonic Motion"},
                {"id": "7.2", "title": "Frequency and Period of SHM"},
                {"id": "7.3", "title": "Representing and Analyzing SHM"},
                {"id": "7.4", "title": "Energy of SHM"},
                {"id": "7.5", "title": "Simple and Physical Pendulums"},
            ]},
            {"id": 8, "title": "Fluids", "topics": [
                {"id": "8.1", "title": "Density"},
                {"id": "8.2", "title": "Pressure"},
                {"id": "8.3", "title": "Fluids and Free-Body Diagrams"},
                {"id": "8.4", "title": "Buoyancy"},
                {"id": "8.5", "title": "Fluid Dynamics"},
            ]},
        ],
    },
    "ap2": {
        "course": "AP Physics 2",
        "units": [
            {"id": 1, "title": "Fluids: Pressure and Forces", "topics": [
                {"id": "1.1", "title": "Density"},
                {"id": "1.2", "title": "Pressure"},
                {"id": "1.3", "title": "Fluids and Free-Body Diagrams"},
                {"id": "1.4", "title": "Buoyancy"},
                {"id": "1.5", "title": "Fluid Dynamics"},
            ]},
            {"id": 2, "title": "Thermodynamics", "topics": [
                {"id": "2.1", "title": "Systems and Fundamental Particles"},
                {"id": "2.2", "title": "Internal Energy and Energy Transfer"},
                {"id": "2.3", "title": "The First Law of Thermodynamics"},
                {"id": "2.4", "title": "Thermodynamic Processes"},
                {"id": "2.5", "title": "The Second Law of Thermodynamics"},
                {"id": "2.6", "title": "Ideal Gases and Kinetic Theory"},
            ]},
            {"id": 3, "title": "Electric Charge, Field, and Potential", "topics": [
                {"id": "3.1", "title": "Electric Charge"},
                {"id": "3.2", "title": "Coulomb's Law and Electric Field"},
                {"id": "3.3", "title": "Electric Flux and Gauss's Law"},
                {"id": "3.4", "title": "Electric Potential"},
                {"id": "3.5", "title": "Capacitors"},
            ]},
            {"id": 4, "title": "Electric Circuits", "topics": [
                {"id": "4.1", "title": "Current, Resistance, and EMF"},
                {"id": "4.2", "title": "Resistive Circuits"},
                {"id": "4.3", "title": "RC Circuits"},
            ]},
            {"id": 5, "title": "Magnetism and Electromagnetism", "topics": [
                {"id": "5.1", "title": "Magnetic Fields and Forces"},
                {"id": "5.2", "title": "Sources of Magnetic Fields"},
                {"id": "5.3", "title": "Electromagnetic Induction"},
                {"id": "5.4", "title": "Inductance and LC Circuits"},
            ]},
            {"id": 6, "title": "Geometric and Physical Optics", "topics": [
                {"id": "6.1", "title": "Waves and Interference"},
                {"id": "6.2", "title": "Reflection and Refraction"},
                {"id": "6.3", "title": "Images from Lenses and Mirrors"},
                {"id": "6.4", "title": "Interference and Diffraction"},
            ]},
            {"id": 7, "title": "Quantum, Atomic, and Nuclear Physics", "topics": [
                {"id": "7.1", "title": "Wave-Particle Duality"},
                {"id": "7.2", "title": "Atomic Energy Levels and Spectra"},
                {"id": "7.3", "title": "Nuclear Physics and Radioactivity"},
                {"id": "7.4", "title": "Mass-Energy Equivalence"},
            ]},
        ],
    },
}

# --------------------------------------------------------------------------------------
# sample questions
# --------------------------------------------------------------------------------------

SAMPLES = {
    "apc-em": {
        "id": "APCE-U1-1.3-Q1",
        "unit": 1, "unit_title": "Electrostatics",
        "topic": "1.3", "topic_title": "Electric Flux and Gauss's Law",
        "additional_topics": ["1.2"],
        "number": 1, "qtype": "mcq",
        "stem": "A point charge $+Q$ sits at the center of a cube of side length $a$. "
                "What is the electric flux through one face of the cube?",
        "choices": [
            {"label": "A", "text": "$\\dfrac{Q}{\\varepsilon_{0}}$"},
            {"label": "B", "text": "$\\dfrac{Q}{6\\varepsilon_{0}}$"},
            {"label": "C", "text": "$\\dfrac{Q}{6a^{2}\\varepsilon_{0}}$"},
            {"label": "D", "text": "$\\dfrac{Q}{a^{2}\\varepsilon_{0}}$"},
        ],
        "answer": "B",
        "solution": "Gauss's law gives the total flux through the closed cube as "
                    "$\\Phi_{E} = \\dfrac{Q}{\\varepsilon_{0}}$. By symmetry the six faces "
                    "share it equally, so one face carries $\\dfrac{Q}{6\\varepsilon_{0}}$.",
        "stem_blocks": [
            {"type": "text",
             "text": "A point charge $+Q$ sits at the center of a cube of side length $a$. "
                     "What is the electric flux through one face of the cube?"},
        ],
        "difficulty": "medium", "tags": ["gauss", "flux", "sample"],
        "source": {"doc": "SAMPLE"},
    },
    "ap1": {
        "id": "AP1-U1-1.3-Q1",
        "unit": 1, "unit_title": "Kinematics",
        "topic": "1.3", "topic_title": "Motion in Two Dimensions",
        "additional_topics": [],
        "number": 1, "qtype": "mcq",
        "stem": "A ball is launched horizontally at $12\\ \\mathrm{m/s}$ from a cliff "
                "$45\\ \\mathrm{m}$ above the ground. Air resistance is negligible. "
                "How far from the base of the cliff does it land?",
        "choices": [
            {"label": "A", "text": "$18\\ \\mathrm{m}$"},
            {"label": "B", "text": "$36\\ \\mathrm{m}$"},
            {"label": "C", "text": "$54\\ \\mathrm{m}$"},
            {"label": "D", "text": "$90\\ \\mathrm{m}$"},
        ],
        "answer": "B",
        "solution": "The vertical fall sets the time: "
                    "$t = \\sqrt{\\dfrac{2h}{g}} = \\sqrt{\\dfrac{2(45)}{10}} = 3\\ \\mathrm{s}$. "
                    "The horizontal distance is then $x = v_{x}t = (12)(3) = 36\\ \\mathrm{m}$.",
        "stem_blocks": [
            {"type": "text",
             "text": "A ball is launched horizontally at $12\\ \\mathrm{m/s}$ from a cliff "
                     "$45\\ \\mathrm{m}$ above the ground. Air resistance is negligible. "
                     "How far from the base of the cliff does it land?"},
        ],
        "difficulty": "easy", "tags": ["projectile", "sample"],
        "source": {"doc": "SAMPLE"},
    },
    "ap2": {
        "id": "AP2-U2-2.4-Q1",
        "unit": 2, "unit_title": "Thermodynamics",
        "topic": "2.4", "topic_title": "Thermodynamic Processes",
        "additional_topics": ["2.3"],
        "number": 1, "qtype": "mcq",
        "stem": "An ideal gas expands from $2.0\\ \\mathrm{m}^{3}$ to $5.0\\ \\mathrm{m}^{3}$ "
                "at a constant pressure of $4.0 \\times 10^{4}\\ \\mathrm{Pa}$. "
                "How much work is done by the gas?",
        "choices": [
            {"label": "A", "text": "$8.0 \\times 10^{4}\\ \\mathrm{J}$"},
            {"label": "B", "text": "$1.2 \\times 10^{5}\\ \\mathrm{J}$"},
            {"label": "C", "text": "$2.0 \\times 10^{5}\\ \\mathrm{J}$"},
            {"label": "D", "text": "$2.8 \\times 10^{5}\\ \\mathrm{J}$"},
        ],
        "answer": "B",
        "solution": "At constant pressure $W = P\\Delta V = (4.0 \\times 10^{4})"
                    "(5.0 - 2.0) = 1.2 \\times 10^{5}\\ \\mathrm{J}$.",
        "stem_blocks": [
            {"type": "text",
             "text": "An ideal gas expands from $2.0\\ \\mathrm{m}^{3}$ to $5.0\\ \\mathrm{m}^{3}$ "
                     "at a constant pressure of $4.0 \\times 10^{4}\\ \\mathrm{Pa}$. "
                     "How much work is done by the gas?"},
        ],
        "difficulty": "medium", "tags": ["thermo", "work", "sample"],
        "source": {"doc": "SAMPLE"},
    },
}


def write_json(path: str, payload, *, force: bool) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and not force:
        return "kept"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return "written"


def make_placeholder(path: str) -> str:
    """A grey box with a cross and a caption, so an empty block is unmistakable."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return "kept"
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=260)
    box = pymupdf.Rect(6, 6, 414, 254)
    page.draw_rect(box, color=(0.62, 0.64, 0.68), width=3)
    page.draw_line(box.tl, box.br, color=(0.62, 0.64, 0.68), width=2)
    page.draw_line(box.tr, box.bl, color=(0.62, 0.64, 0.68), width=2)
    page.insert_text(pymupdf.Point(126, 132), "IMAGE PLACEHOLDER",
                     fontsize=22, fontname="helv", color=(0.35, 0.37, 0.41))
    page.insert_text(pymupdf.Point(150, 162), "upload a figure to replace this",
                     fontsize=12, fontname="helv", color=(0.45, 0.47, 0.51))
    page.get_pixmap(dpi=150).save(path)
    doc.close()
    return "written"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing banks and taxonomies")
    args = parser.parse_args()

    for course_id, taxonomy in TAXONOMIES.items():
        course = courses_mod.get(course_id)
        tax_path = course.path(course.taxonomy)
        print(f"{course_id}: taxonomy {write_json(tax_path, taxonomy, force=args.force)}")

        sample = SAMPLES[course_id]
        bank_path = course.path(course.bank)
        if os.path.exists(bank_path) and not args.force:
            print(f"{course_id}: bank kept")
            continue
        bank = {
            "version": 1,
            "course": taxonomy["course"],
            "questions": [{
                **sample,
                "images": [], "layout": "inline", "needs_review": False,
            }],
        }
        print(f"{course_id}: bank {write_json(bank_path, bank, force=args.force)}")

    placeholder = os.path.join(courses_mod.MEDIA_DIR, "placeholder.png")
    print(f"placeholder {make_placeholder(placeholder)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
