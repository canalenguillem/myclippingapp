// Registro de motivos gráficos. Cada motivo es una función ({id, item, t0, at, t1}) → {html, css, script} con los
// tiempos YA en tiempo de salida. Añadir un motivo = una entrada aquí + su esquema en `contract.mjs`.
import { emojiMotif } from "./emoji.mjs";
import { imageMotif } from "./image.mjs";
import { keywordMotif } from "./keyword.mjs";

export const MOTIFS = {
  keyword: keywordMotif,
  emoji: emojiMotif,
  image: imageMotif,
};
