Rive assets live here.

Expected filenames (used by the UI components):
- vera_swarm_core_enhanced.riv
- vera_aperture_logo.riv

Source SVG assets to import into Rive:
- vera_swarm_core.svg
- vera_swarm_satellite.svg
- vera_sliced_assets.svg

If the `.riv` files are missing or invalid, the UI falls back to the existing glow/text styles.

Rive state machine expectations:
- Swarm indicator: state machine `AgentFlow` with inputs `AgentState` (0 idle, 1 swarm, 2 quorum, 3 error) and `Intensity` (0..1).
- VERA logo: state machine `LogoFlow` with inputs `LogoState` (0 idle, 1 listening, 2 swarm, 3 quorum, 4 error), `Intensity`, and `SpeechPulse`.
