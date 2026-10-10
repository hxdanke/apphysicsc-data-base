"""The 21 table-style questions, transcribed by hand from the printed pages.

Each entry gives the two (or three) header cells and the four option rows.  Text
is written in the bank's house LaTeX style: prose stays plain, physics fragments
are wrapped in $...$ with proper subscripts.  This is the authoritative table
data -- the geometry detector only tells us *which* questions are tables.
"""

TABLES = {
    # 1.1 Scalars and Vectors -- Magnitude | Direction
    "EB3-U1-1.1-Q2": {
        "headers": ["Magnitude", "Direction"],
        "rows": [
            [r"$4\ \mathrm{m/s}$", r"$45^{\circ}$ counterclockwise from the $+x$-direction"],
            [r"$4\ \mathrm{m/s}$", r"$45^{\circ}$ clockwise from the $+x$-direction"],
            [r"$4\sqrt{2}\ \mathrm{m/s}$", r"$45^{\circ}$ counterclockwise from the $+x$-direction"],
            [r"$4\sqrt{2}\ \mathrm{m/s}$", r"$45^{\circ}$ clockwise from the $+x$-direction"],
        ],
    },
    # 1.2 Representations of Motion -- Velocities | Accelerations
    "EB3-U1-1.2-Q4": {
        "headers": ["Velocities", "Accelerations"],
        "rows": [
            ["Same direction", "Same direction"],
            ["Same direction", "Opposite directions"],
            ["Opposite directions", "Same direction"],
            ["Opposite directions", "Opposite directions"],
        ],
    },
    # 2.3 Newton's Third Law -- tension comparison
    "EB3-U2-2.3-Q8": {
        "headers": ["Both blocks in motion", "After hanging block stops"],
        "rows": [
            [r"$T_h = T_s > 0$", r"$T_h = T_s = 0$"],
            [r"$T_h = T_s > 0$", r"$T_s > T_h = 0$"],
            [r"$T_h > T_s > 0$", r"$T_h = T_s = 0$"],
            [r"$T_h > T_s > 0$", r"$T_s > T_h = 0$"],
        ],
    },
    # 2.4 Newton's First Law -- Before P | After P
    "EB3-U2-2.4-Q1": {
        "headers": ["Before P", "After P"],
        "rows": [
            ["Constant velocity, because the horizontal forces are balanced.",
             "Increasing velocity, because the horizontal forces are now unbalanced."],
            ["Constant velocity, because the horizontal forces are balanced.",
             "Constant velocity, because the object does not have any force of "
             "friction exerted on it to reduce its velocity."],
            ["Decreasing velocity, because the tension is not greater than the "
             "force of kinetic friction.",
             "Increasing velocity, because the horizontal forces are now unbalanced."],
            ["Decreasing velocity, because the tension is not greater than the "
             "force of kinetic friction.",
             "Constant velocity, because the object does not have any force of "
             "friction exerted on it to reduce its velocity."],
        ],
    },
    # 2.9 Resistive Forces -- initial acceleration | terminal speed
    "EB3-U2-2.9-Q1": {
        "headers": ["Initial Acceleration", "Terminal Speed"],
        "rows": [
            [r"$a_{0,A} = a_{0,B}$", r"$v_{T,A} = v_{T,B}$"],
            [r"$a_{0,A} = a_{0,B}$", r"$v_{T,A} < v_{T,B}$"],
            [r"$a_{0,A} < a_{0,B}$", r"$v_{T,A} = v_{T,B}$"],
            [r"$a_{0,A} < a_{0,B}$", r"$v_{T,A} < v_{T,B}$"],
        ],
    },
    # 2.9 Resistive Forces -- acceleration | resistive force
    "EB3-U2-2.9-Q3": {
        "headers": ["Acceleration", "Resistive Force"],
        "rows": [
            ["Decreasing", "Decreasing"],
            ["Decreasing", "Increasing"],
            ["Increasing", "Decreasing"],
            ["Increasing", "Increasing"],
        ],
    },
    # 2.9 Resistive Forces -- terminal speed | half-terminal time
    "EB3-U2-2.9-Q5": {
        "headers": [r"$v_T$", r"$t_{0.5}$"],
        "rows": [
            ["Decreases", "Decreases"],
            ["Decreases", "No change"],
            ["Increases", "Decreases"],
            ["Increases", "No change"],
        ],
    },
    # 3.4 Conservation of Energy -- final velocities | final energies
    "EB3-U3-3.4-Q3": {
        "headers": ["Final velocities", "Final energies"],
        "rows": [
            [r"$v_A = v_B$", r"$E_A > E_B$"],
            [r"$v_A = v_B$", r"$E_A < E_B$"],
            [r"$v_A > v_B$", r"$E_A = E_B$"],
            [r"$v_A > v_B$", r"$E_A = E_B$"],
        ],
    },
    # 3.4 Conservation of Energy -- speed of ship | PE of system
    "EB3-U3-3.4-Q5": {
        "headers": ["Speed of ship", "Potential energy of system"],
        "rows": [
            ["Less", "Less"],
            ["Less", "Same"],
            ["Greater", "Less"],
            ["Greater", "Same"],
        ],
    },
    # 3.5 Power -- work | time
    "EB3-U3-3.5-Q5": {
        "headers": ["Work", "Time"],
        "rows": [
            [r"$W_2 = W_1$", r"$t_2 > t_1$"],
            [r"$W_2 > W_1$", r"$t_2 = t_1$"],
            [r"$W_2 = W_1$", r"$t_2 = t_1$"],
            [r"$W_2 > W_1$", r"$t_2 > t_1$"],
        ],
    },
    # 3.5 Power -- pull power | normal power
    "EB3-U3-3.5-Q7": {
        "headers": [r"$P_{\text{pull}}$", r"$P_{\text{norm}}$"],
        "rows": [
            ["Increases", "Decreases"],
            ["Increases", "Remains the same"],
            ["Remains the same", "Decreases"],
            ["Remains the same", "Remains the same"],
        ],
    },
    # 4.2 Impulse and Momentum -- three-column table
    "EB3-U4-4.2-Q3": {
        "headers": [r"Maximum of $F_h$", "Duration of collision", "Area under graph"],
        "rows": [
            ["Increases", "Decreases", "Increases"],
            ["Decreases", "Increases", "Remains the same"],
            ["Increases", "Decreases", "Remains the same"],
            ["Decreases", "Remains the same", "Decreases"],
        ],
    },
    # 4.2 Impulse and Momentum -- work | impulse
    "EB3-U4-4.2-Q4": {
        "headers": ["Work", "Impulse"],
        "rows": [
            [r"$W_1 < W_2$", r"$J_1 < J_2$"],
            [r"$W_1 < W_2$", r"$J_1 > J_2$"],
            [r"$W_1 > W_2$", r"$J_1 < J_2$"],
            [r"$W_1 > W_2$", r"$J_1 > J_2$"],
        ],
    },
    # 4.3 Collisions -- centre-of-mass speeds | impulses
    "EB3-U4-4.3-Q2": {
        "headers": ["Center of mass speeds", "Magnitude of the impulses exerted on Block B"],
        "rows": [
            [r"$v_1 = v_2$", r"$J_1 > J_2$"],
            [r"$v_1 = v_2$", r"$J_1 = J_2$"],
            [r"$v_1 > v_2$", r"$J_1 > J_2$"],
            [r"$v_1 > v_2$", r"$J_1 = J_2$"],
        ],
    },
    # 4.3 Collisions -- velocity components
    "EB3-U4-4.3-Q9": {
        "headers": [r"$v_x$", r"$v_y$"],
        "rows": [
            [r"$v_0(1 - \cos \theta)$", r"$-v_0 \sin \theta$"],
            [r"$-v_0 \cos \theta$", r"$-v_0 \sin \theta$"],
            [r"$v_0$", r"$-v_0$"],
            [r"$0$", r"$0$"],
        ],
    },
    # 5.1 Rotational Kinematics -- angular displacement | acceleration
    "EB3-U5-5.1-Q7": {
        "headers": ["Angular displacement", "Angular acceleration"],
        "rows": [
            ["Increasing at a decreasing rate", "Negative and increasing in magnitude"],
            ["Increasing at a decreasing rate", r"Maximum at $t = 0$ and decreasing to zero"],
            ["Negative and increasing in magnitude", "Negative and increasing in magnitude"],
            ["Negative and increasing in magnitude", r"Maximum at $t = 0$ and decreasing to zero"],
        ],
    },
    # 5.2 Connecting Linear and Rotational Motion
    "EB3-U5-5.2-Q8": {
        "headers": ["Angular speed", "Magnitude of angular acceleration"],
        "rows": [
            ["The same for both objects", "The same for both objects"],
            ["The same for both objects", "Greater for the carrot"],
            ["Greater for the carrot", "The same for both objects"],
            ["Greater for the carrot", "Greater for the carrot"],
        ],
    },
    # 7.1 Simple Harmonic Motion -- equilibrium | restoring force
    "EB3-U7-7.1-Q4": {
        "headers": ["Equilibrium Position", "Linear Restoring Force"],
        "rows": [
            ["Both scenarios", "Neither scenario"],
            ["Both scenarios", "Scenario 2 only"],
            ["Scenario 2 only", "Neither scenario"],
            ["Scenario 2 only", "Scenario 2 only"],
        ],
    },
    # 7.3 Representing and Analyzing SHM -- period | maximum speed
    "EB3-U7-7.3-Q1": {
        "headers": ["Period", "Maximum Speed"],
        "rows": [
            [r"Less than $T_0$", r"Less than $v_0$"],
            [r"Less than $T_0$", r"Equal to $v_0$"],
            [r"Equal to $T_0$", r"Less than $v_0$"],
            [r"Equal to $T_0$", r"Equal to $v_0$"],
        ],
    },
    # 7.4 Energy of SHM -- amplitude | maximum speed (stacked fractions)
    "EB3-U7-7.4-Q1": {
        "headers": ["Amplitude", "Maximum Speed"],
        "rows": [
            [r"$\dfrac{A_1}{2}$", r"$\dfrac{v_{\max,1}}{2}$"],
            [r"$\dfrac{A_1}{2}$", r"$\dfrac{v_{\max,1}}{\sqrt{2}}$"],
            [r"$A_1$", r"$\dfrac{v_{\max,1}}{2}$"],
            [r"$A_1$", r"$\dfrac{v_{\max,1}}{\sqrt{2}}$"],
        ],
    },
    # 7.4 Energy of SHM -- total energy | maximum KE
    "EB3-U7-7.4-Q4": {
        "headers": ["Total Mechanical Energy", "Maximum Kinetic Energy"],
        "rows": [
            [r"$2E_1$", r"$K_1$"],
            [r"$2E_1$", r"$2K_1$"],
            [r"$4E_1$", r"$2K_1$"],
            [r"$4E_1$", r"$4K_1$"],
        ],
    },
}
