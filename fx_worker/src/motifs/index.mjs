// Registro de motivos gráficos. Cada motivo es una función ({id, item, t0, at, t1}) → {html, css, script} con los
// tiempos YA en tiempo de salida. Añadir un motivo = una entrada aquí + su esquema en `contract.mjs`.
import { counterMotif } from "./counter.mjs";
import { emojiMotif } from "./emoji.mjs";
import { imageMotif } from "./image.mjs";
import { keywordMotif } from "./keyword.mjs";
import { lowerThirdMotif } from "./lowerThird.mjs";
import { strikeMotif } from "./strike.mjs";

export const MOTIFS = {
  keyword: keywordMotif,
  emoji: emojiMotif,
  image: imageMotif,
  counter: counterMotif,
  strike: strikeMotif,
  lower_third: lowerThirdMotif,
};
