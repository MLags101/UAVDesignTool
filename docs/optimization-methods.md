# Optimization workbench: methods and qualification

This document is the implementation contract and reference baseline. The workbench
is conceptual/preliminary design software. A solver success flag is not physical
validation. Release qualification is tracked in `optimization-validation.md`.

## Sources

- NDARC design/analysis architecture: https://rotorcraft.arc.nasa.gov/ndarc/index.php
- SUAVE coupled sizing example: https://suave.stanford.edu/tutorials/jet_optimization.html
- NASA reference configurations: https://www.nasa.gov/reference/uam-refs/
- OpenMDAO: https://openmdao.org/newdocs/versions/latest/index.html
- AeroSandbox: https://github.com/peterdsharpe/AeroSandbox
- VSPAERO: https://www.nasa.gov/reference/openvsp-vspaero-basics/
- RocketPy: https://docs.rocketpy.org/en/latest/
- US Standard Atmosphere 1976: https://ntrs.nasa.gov/citations/19770009539
- SciPy DE: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html
- pymoo NSGA-II: https://pymoo.org/algorithms/moo/nsga2.html

## Reference fixtures (specified before implementation)

1. Atmosphere: sea-level density 1.225 kg/m³ (0.1% tolerance), 11 km
   temperature 216.65 K (0.01 K), 20 km pressure 5474.89 Pa (0.2%).
2. Ideal hover: T=10 N, rho=1.225 kg/m³, disk area=1 m² gives
   P=T**1.5/sqrt(2*rho*A)=20.203050891 W (1e-8 relative).
3. Parabolic polar: minimum drag occurs when induced drag equals parasite
   drag; CL=sqrt(CD0*pi*e*AR) (1e-8 relative).
4. Battery circuit: V_oc=20 V, R=0.1 ohm, P=360 W gives I=20 A,
   loaded voltage=18 V; P>V_oc²/(4R) has no real operating point.
5. Constant-g ballistic coast: v0=100 m/s has apex rise v0²/(2g)
   and apex time v0/g; integration tolerance 0.1%.
6. Constrained optimizer: minimize (x-2)² subject to x<=1, x in [0,3].
   Feasible optimum x=1, objective=1 (1e-3 tolerance).
7. Pareto: objectives x² and (x-2)² on [0,2]. Every point is nondominated;
   every returned point must be feasible. No particular stochastic population
   or ordering is required.

## Model conventions

SI throughout, with display conversion at the boundary. Residual >= 0 means
constraint satisfied. Source maps are interpolated only inside their domain.
Hardware records are immutable during a run. Unknown inputs and metrics fail
validation. Finite bounds and explicit objective/constraint scales are required.

Sizing closes mass and energy with damped iteration; closure failure invalidates
a candidate. Structure, installed power and stored energy contribute mass.
Wing spar caps use one section model for bending stress and cantilever
deflection: two caps, uniform lift, and a tip limit measured on the semi-span.
Rocket airframe checks add fixed-free Euler buckling of the body tube to the
thin-wall axial stress. Multirotor axial climb uses momentum theory once;
edgewise flight still adds climb power to the level-flight induced power.
Empirical technology assumptions are editable and are not measured part data.
Helicopter and VTOL calculations do not establish dynamic flight stability.
Rocket point-mass calculations do not establish attitude dynamics.

Runs record an input hash, model version, solver settings and seed. Uncertainty
uses user-supplied distributions; scenario robustness is not a probability claim.
Published system-level comparisons require matching assumptions and separately
recorded tolerances, not a universal percentage accuracy claim.

## Preview 0.2 equilibrium fixtures

`tests/fixtures/optimization/rotor-trim.json` and `transition-forces.json` record
inputs, equations, source links and acceptance tolerances specified before the
corresponding solver changes. They verify analytical equilibrium, not vehicle
performance accuracy. Rotor thrust and two hub moments use collective and cyclic
harmonics. Preview 0.3 adds rigid-aircraft six-component equilibrium in
`helicopter-equilibrium.json`; this verifies equations, not measured accuracy. Transition checks
apply Newton's equations to the prescribed planar schedule and expose lift-system
braking tilt rather than silently discarding negative axial thrust demand.

## Preview 0.3 references

- `propulsion-reference.json`: selected measured UIUC APC 10x7 coefficient data,
  plus separately identified synthetic DC-equivalent motor circuit identities.
  The circuit is not a measured motor/propeller combination.
- `rocketpy-vertical.json`: matched vertical point-mass case with RocketPy 1.13.0.
  Core apogee 868.38 m versus reference 869.12 m, within the case's 2 m tolerance.
  This does not validate CP, attitude or parachute descent.
- `caradonna-tung.json`: NASA-TM-81232 experiment description and Figure 4,
  [NASA source](https://ntrs.nasa.gov/citations/19820004169). Inputs and a 1 degree
  collective screening tolerance were recorded before executing the comparison.
  The unchanged rotor model predicts 6.6125 degrees versus measured 8 degrees:
  **failed**, error -1.3875 degrees. No coefficients or tolerances were adjusted.
  Dimensionless hover similarity, neglected precone and uniform inflow are declared
  in the fixture. Run `python tests/check_published_rotor.py` to reproduce; its
  nonzero exit is an engineering qualification failure, separate from regression.

NASA UAM concept report Table 3 was inspected for potential configuration checks.
Its published figure of merit would be an input to this application's momentum
model, so reproducing hover power from that input would not independently validate
rotor efficiency or vehicle sizing. Such a calculation is not counted as a passed
vehicle benchmark.
