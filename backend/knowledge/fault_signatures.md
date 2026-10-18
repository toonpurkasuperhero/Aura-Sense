# Rotating-machine fault signatures (reference for AuraSense agents)

1x = running speed in Hz (rpm / 60). "Radial" = X/Y axes, "axial" = Z axis (along the shaft).

| Fault | Vibration signature | Temperature | Sound | Visual clues |
|---|---|---|---|---|
| Imbalance (mass on rotor, dirt build-up, broken/bent blade) | Dominant 1x radial, steady phase, little 2x; amplitude rises with speed squared | Normal | Rhythmic "whump" at 1x | Dirt/scale on fan blades, missing balance weight, damaged blade, foreign object stuck on hub |
| Misalignment (angular / parallel) | High 2x (often > 50% of 1x), significant AXIAL vibration, 1x also present | Coupling/bearing warm | Steady growl | Worn/cracked coupling insert, rubber dust under coupling, shifted motor feet, uneven shims |
| Mechanical looseness | Many harmonics (2x, 3x, 4x ...), sometimes 0.5x sub-harmonics, erratic; high crest factor | Normal | Rattling, knocking | Loose/missing bolts, cracked base, fretting marks (red-brown powder) at joints, soft foot |
| Rolling-element bearing defect | Non-integer high-frequency peaks (BPFO/BPFI/BSF), rising kurtosis and crest factor, broadband high-frequency noise; late stage raises 1x | Rises as it worsens (friction) | Early: high-pitch squeal/whine; late: grinding, rumbling, periodic clicks | Discoloration/heat marks on housing, grease leakage, rust (fretting corrosion), metal particles |
| Lubrication problem (dry / over-greased) | Broadband high-frequency rise, kurtosis normal | Bearing temperature rises | Squeal / hiss | Grease purge on seals, dry dark grease, no grease at fitting |
| Belt problems (slip, wear, misaligned pulleys) | Peaks at belt frequency (below 1x) and its harmonics | Pulley warm | Chirp/squeal at start | Glazed/cracked belt, black belt dust, pulley grooves worn |
| Electrical (stator, rotor bar, unbalanced supply, soft foot) | Peak at 2x line frequency (100 Hz on 50 Hz supply); rotor-bar sidebands around 1x | Winding/frame overheating | Magnetic hum that stops instantly when power is cut | Burnt varnish smell, discoloured terminal box, burnt windings, damaged cables |
| Overload / cooling failure | Vibration may be normal | Frame temperature well above baseline | Strained hum | Blocked fan cover, dust caked on fins, broken cooling fan |
| Pump cavitation | Broadband random high-frequency vibration | Normal or slightly warm | "Gravel / marbles" crackling | Pitting on impeller, low suction pressure, vapour at suction |
| Structural resonance | Very high amplitude at one frequency, changes strongly with speed | Normal | Loud drone | Cracked welds/base, flexing frame |
| Fire / burning (flame sensor tripped) | May be normal; smoke/heat often follows a seized bearing, slipping belt or shorted winding | Rising fast | Crackling, hiss | Smoke, flame, charring, melted insulation, burnt belt dust |
| High humidity / condensation (RH > 85%) | Not visible in vibration | Normal | Normal | Water droplets, rust bloom, corrosion at terminals, damp windings (low insulation resistance) |
| Corrosion / environmental damage | Not directly visible in vibration until it causes looseness or bearing damage | Normal | Normal | Rust on casing, flaking paint, corrosion at terminals and feet, water ingress marks |

## Severity guide (for small/medium machines, use trend vs. own baseline)
- Vibration RMS < 2x baseline and stable: LOW, monitor.
- 2-4x baseline or new harmonic family: MEDIUM, plan repair this week.
- > 4x baseline, rising quickly, or temperature +15 °C: HIGH, repair within 24-48 h, reduce load.
- Impacting + rapid temperature rise, smoke/burning smell, or grinding: CRITICAL, stop the machine now.
- FLAME SENSOR TRIPPED: always CRITICAL. Stop, isolate power, use a CO2 / dry-powder extinguisher (never water on electrical equipment), evacuate if it spreads.

## General safety rules (all repairs)
- Lock-out / tag-out (LOTO) of the electrical supply before touching the machine; verify zero energy.
- Wait for rotation to stop completely; block rotating parts against movement.
- Let hot surfaces cool (> 50 °C causes burns).
- PPE: safety glasses, gloves, safety shoes; hearing protection near loud machines.
- Never remove guards while the machine is running.
