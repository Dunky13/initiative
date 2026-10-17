/**
 * What this widget calls itself, in every language it supports.
 *
 * Names and option labels live in the module rather than in the app's locale
 * files: a marketplace widget has to be able to name itself without an app
 * release, and the built-ins get no special treatment. Binding *source* labels
 * stay plugin-owned — they name our endpoints and are shared by every widget.
 */
const meta = {
  name: {
    en: "Stat",
    de: "Kennzahl",
    es: "Estadística",
    fr: "Statistique",
  },
  description: {
    en: "A single headline number, with an optional trend against the previous period.",
    de: "Eine einzelne Kennzahl, wahlweise mit Trend gegenüber dem Vorzeitraum.",
    es: "Una única cifra destacada, con una tendencia opcional respecto al periodo anterior.",
    fr: "Un seul chiffre clé, avec une tendance facultative par rapport à la période précédente.",
  },
  options: {
    format: {
      label: {
        en: "Format",
        de: "Format",
        es: "Formato",
        fr: "Format",
      },
      values: {
        plain: {
          en: "Plain number",
          de: "Einfache Zahl",
          es: "Número simple",
          fr: "Nombre simple",
        },
        percent: {
          en: "Percentage",
          de: "Prozent",
          es: "Porcentaje",
          fr: "Pourcentage",
        },
        currency: {
          en: "Currency",
          de: "Währung",
          es: "Moneda",
          fr: "Devise",
        },
        duration: {
          en: "Duration",
          de: "Dauer",
          es: "Duración",
          fr: "Durée",
        },
      },
    },
    pick: {
      label: {
        en: "Which number",
        de: "Welche Zahl",
        es: "Qué número",
        fr: "Quel chiffre",
      },
      values: {
        total: {
          en: "Total of everything",
          de: "Summe von allem",
          es: "Total de todo",
          fr: "Total de tout",
        },
        largest: {
          en: "The largest group",
          de: "Die größte Gruppe",
          es: "El grupo más grande",
          fr: "Le plus grand groupe",
        },
        first: {
          en: "The first group",
          de: "Die erste Gruppe",
          es: "El primer grupo",
          fr: "Le premier groupe",
        },
      },
    },
    trend: {
      label: {
        en: "Trend",
        de: "Trend",
        es: "Tendencia",
        fr: "Tendance",
      },
      values: {
        off: {
          en: "Just the number",
          de: "Nur die Zahl",
          es: "Solo el número",
          fr: "Le chiffre seul",
        },
        on: {
          en: "Show change and a sparkline",
          de: "Veränderung und Verlaufslinie zeigen",
          es: "Mostrar el cambio y una minigráfica",
          fr: "Afficher l'évolution et une courbe",
        },
      },
    },
    direction: {
      label: {
        en: "Rising is",
        de: "Steigend ist",
        es: "Subir es",
        fr: "En hausse, c'est",
      },
      values: {
        up_good: {
          en: "Good",
          de: "Gut",
          es: "Bueno",
          fr: "Bon",
        },
        down_good: {
          en: "Bad",
          de: "Schlecht",
          es: "Malo",
          fr: "Mauvais",
        },
      },
    },
    target: {
      label: { en: "Target", de: "Ziel", es: "Objetivo", fr: "Objectif" },
    },
    target_date: {
      label: {
        en: "Target date",
        de: "Zieldatum",
        es: "Fecha objetivo",
        fr: "Date cible",
      },
    },
  },
};

/**
 * This widget's own output, in every language it speaks.
 *
 * Beside `meta` and for the same reason: a column heading and an empty-state
 * line are the widget's words, and there is no app locale file a marketplace
 * widget could add itself to. The host hands `render` the viewer's language
 * tag; `say` picks from here. Formatting numbers and dates is still the host's
 * job — the sandbox has no locale data and no timezone.
 */
const strings = {
  target: { en: "Target", de: "Ziel", es: "Objetivo", fr: "Objectif" },
  reached: { en: "Reached", de: "Erreicht", es: "Alcanzado", fr: "Atteint" },
  missed: { en: "Missed", de: "Verfehlt", es: "No alcanzado", fr: "Manqué" },
  onTrack: { en: "On track", de: "Im Plan", es: "En camino", fr: "En bonne voie" },
  behind: { en: "Behind", de: "Im Rückstand", es: "Con retraso", fr: "En retard" },
  // "{n}" is how far there is still to go.
  toGo: { en: "{n} to go", de: "noch {n}", es: "faltan {n}", fr: "encore {n}" },
  noRows: {
    en: "Nothing to show",
    de: "Nichts anzuzeigen",
    es: "Nada que mostrar",
    fr: "Rien à afficher",
  },
  noNumeric: {
    en: "No numeric column to report",
    de: "Keine Zahlenspalte zum Anzeigen",
    es: "Ninguna columna numérica que mostrar",
    fr: "Aucune colonne numérique à afficher",
  },
  total: { en: "Total", de: "Gesamt", es: "Total", fr: "Total" },
  of: { en: "of", de: "von", es: "de", fr: "sur" },
  points: { en: "points", de: "Punkte", es: "puntos", fr: "points" },
};

/** One day, in milliseconds. */
const DAY = 86400000;

/**
 * The target the options set, and the moment it is due: the end of its day.
 * `null` without a target.
 */
function targetOf(config) {
  const value = config.target === undefined || config.target === "" ? NaN : Number(config.target);
  if (!Number.isFinite(value)) return null;
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(config.target_date || "");
  const due = day ? Date.UTC(Number(day[1]), Number(day[2]) - 1, Number(day[3])) + DAY - 1 : null;
  return { value: value, due: due };
}

/**
 * Where a number stands against its target.
 *
 * Reached once it gets there, and missed once the day has passed without it.
 * Before then, a straight line through the points drawn so far says whether it
 * gets there by the day: on track, or behind. With no day, or too few points to
 * draw a line through, it is only so far to go. `down` is a target to come down
 * to rather than to climb to.
 *
 * @param {{t: number, y: number}[]} points earliest first, `t` in epoch ms
 */
function pace(points, current, target, due, down) {
  if (down ? current <= target : current >= target) return "reached";
  if (due !== null && due < Date.now()) return "missed";
  if (due === null || points.length < 2) return "toGo";
  // In days from the first point, which keeps the sums well inside a double.
  const origin = points[0].t;
  const days = points.map((point) => (point.t - origin) / DAY);
  let meanT = 0;
  let meanY = 0;
  for (let index = 0; index < points.length; index++) {
    meanT += days[index];
    meanY += points[index].y;
  }
  meanT /= points.length;
  meanY /= points.length;
  let across = 0;
  let spread = 0;
  for (let index = 0; index < points.length; index++) {
    across += (days[index] - meanT) * (points[index].y - meanY);
    spread += (days[index] - meanT) * (days[index] - meanT);
  }
  if (spread === 0) return "toGo";
  const lands = meanY + (across / spread) * ((due - origin) / DAY - meanT);
  return (down ? lands <= target : lands >= target) ? "onTrack" : "behind";
}

/** The tone each standing is drawn in. "To go" keeps the widget's own. */
const PACE_TONES = {
  reached: "positive",
  onTrack: "positive",
  behind: "warning",
  missed: "negative",
};

/** A number as plain text: whole, or to two places. */
const plain = (value) => String(Number.isInteger(value) ? value : Math.round(value * 100) / 100);

/** A standing in words: "On track", or how far there is still to go. */
function standing(say, state, current, target) {
  if (state !== "toGo") return say(state);
  return say("toGo").replace("{n}", plain(Math.abs(target - current)));
}

/**
 * Built-in: Stat — one big number, and what it is doing.
 *
 * Like every built-in, this is an ordinary widget module: it runs in the same
 * sandbox as an installed listing's widget, with the same capabilities (none)
 * and the same contract. Being in this repo buys it review, not privilege.
 *
 * The trend is why the widget is more than a number in a box. When the binding
 * is bucketed by day, the rows *are* a time series, so the widget splits them
 * into two halves and reports the later against the earlier — which is what
 * anyone reading a dashboard actually wants to know, and what the description
 * has promised since the first release without delivering it.
 *
 * @param {import("../dataShapes").WidgetData} data
 * @param {import("../dataShapes").WidgetConfig} config
 */
function render(data, config, context) {
  // The viewer's language, and this module's own words in it. An older host
  // that passes no context leaves this at English rather than failing.
  const lang = context?.locale || "en";
  const say = (key) => {
    const entry = strings[key] || {};
    return entry[lang] || entry[lang.split("-")[0]] || entry.en || key;
  };
  const format = config.format || "plain";
  const pick = config.pick || "total";
  const wantTrend = config.trend === "on";
  const deltaGood = config.direction === "down_good" ? "down" : "up";

  const empty = (message) => ({ v: 1, scene: { kind: "empty", message } });

  const metric = (value, label, caption, extra) => {
    const node = {
      kind: "metric",
      value: Number.isFinite(value) ? value : 0,
      label: label || undefined,
      caption: caption || undefined,
      format: format,
    };
    if (extra) {
      for (const key in extra) node[key] = extra[key];
    }
    return node;
  };

  const scene = (node) => ({ v: 1, scene: node });

  const goal = targetOf(config);

  /** The number against its target, in the caption and its tone. Which way is
   *  better is the same answer the trend chip reads. */
  const aimed = (node, current, points) => {
    if (!goal) return node;
    const state = pace(points, current, goal.value, goal.due, deltaGood === "down");
    node.caption = `${say("target")} ${plain(goal.value)} · ${standing(say, state, current, goal.value)}`;
    if (PACE_TONES[state]) node.tone = PACE_TONES[state];
    return node;
  };

  /** The number above its own history. A `stack` rather than a bespoke node:
   *  the vocabulary already composes, and the sparkline is an ordinary series
   *  the renderer already knows how to draw. */
  const withSparkline = (node, points) => {
    if (!wantTrend || points.length < 3) return scene(node);
    return scene({
      kind: "stack",
      direction: "column",
      gap: "sm",
      // The number leads; the line is context under it.
      weights: [2, 1],
      children: [
        node,
        {
          kind: "series",
          mark: "line",
          showLegend: false,
          series: [{ name: node.label || "", points: points, tone: "accent" }],
        },
      ],
    });
  };

  /** Later half against earlier half, as a fraction. Null when there is not
   *  enough history to make the comparison mean anything — a made-up baseline
   *  would read as a real one. */
  const changeOver = (values) => {
    if (values.length < 4) return null;
    const middle = Math.floor(values.length / 2);
    let earlier = 0;
    let later = 0;
    for (let index = 0; index < middle; index++) earlier += values[index];
    for (let index = middle; index < values.length; index++) later += values[index];
    if (earlier <= 0) return null;
    return (later - earlier) / earlier;
  };

  // Which columns fill this widget's slots, resolved by the host.
  const slots = context?.slots || {};
  const valueAt = (slots.value || [])[0];
  const labelAt = (slots.label || [])[0];

  const rows = data.rows || [];
  if (!rows.length) return empty(say("noRows"));
  if (valueAt === undefined) return empty(say("noNumeric"));

  const number = (row) => (typeof row[valueAt] === "number" ? row[valueAt] : 0);
  const name = (row) =>
    labelAt !== undefined && row[labelAt] !== null ? String(row[labelAt]) : undefined;
  const values = rows.map(number);
  const total = values.reduce((sum, value) => sum + value, 0);
  const heading = data.columns?.[valueAt] ? data.columns[valueAt].name : undefined;

  // A label that orders — a date — makes this a time series: report the total,
  // say how it moved, and draw the shape underneath. A label that does not
  // order has no sequence to read a change from, so none is claimed.
  const overTime =
    labelAt !== undefined && data.columns?.[labelAt]
      ? data.columns[labelAt].type === "date"
      : false;

  if (overTime) {
    const ordered = rows.slice().sort((a, b) => (a[labelAt] || 0) - (b[labelAt] || 0));
    const change = changeOver(ordered.map(number));
    // The total as it stood after each period, which is what a target is
    // reached along.
    let running = 0;
    const climbed = [];
    for (const row of ordered) {
      running += number(row);
      if (typeof row[labelAt] === "number") climbed.push({ t: row[labelAt], y: running });
    }
    const node = aimed(
      metric(
        total,
        heading,
        ordered.length + " " + say("points"),
        change === null ? undefined : { delta: change, deltaGood: deltaGood }
      ),
      total,
      climbed
    );
    return withSparkline(
      node,
      ordered.map((row, index) => ({ x: index + 1, y: number(row) }))
    );
  }

  if (pick === "largest") {
    let best = rows[0];
    for (const row of rows) if (number(row) > number(best)) best = row;
    return scene(
      aimed(metric(number(best), name(best) || heading, say("of") + " " + total), number(best), [])
    );
  }
  if (pick === "first") {
    return scene(
      aimed(
        metric(number(rows[0]), name(rows[0]) || heading, say("of") + " " + total),
        number(rows[0]),
        []
      )
    );
  }
  return scene(aimed(metric(total, heading || say("total")), total, []));
}
