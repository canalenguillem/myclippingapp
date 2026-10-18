// Presets de estilo. `editorial` es el ADN de los vídeos de referencia (conocimiento_motion_video.md §5 y §7);
// `hormozi` y `minimal` vienen del fx_worker viejo y no llevan banda.
export const PRESETS = {
  editorial: {
    band: true,
    paper: "#F3EEE2",
    ink: "#1D1A17",
    accent: "#DA2E09",
    inactiveAlpha: 0.38, // palabras aún no dichas
    sansSize: 64,
    serifSize: 62,
    uppercaseSerif: false,
    stroke: false,
    activeScale: 1.05,
    hookColor: "#FFFFFF",
  },
  hormozi: {
    band: false,
    ink: "#FFFFFF",
    accent: "#FFD400",
    inactiveAlpha: 1,
    sansSize: 76,
    serifSize: 72,
    uppercaseSerif: true,
    stroke: true,
    activeScale: 1.14,
    hookColor: "#FFD400",
  },
  minimal: {
    band: false,
    ink: "#FFFFFF",
    accent: "#FFFFFF",
    inactiveAlpha: 1,
    sansSize: 62,
    serifSize: 60,
    uppercaseSerif: false,
    stroke: false,
    activeScale: 1,
    hookColor: "#FFFFFF",
  },
};

export const getPreset = (name) => PRESETS[name] ?? PRESETS.editorial;
