"""Engineering chart recipes (pillar D) — taught, not tooled.

One read tool serving worked templates beats 25 bespoke chart tools:
the catalog stays small and the model composes. Vega-Lite recipes are
chart_spec-ready; `py` recipes run in the kernel (matplotlib/scipy)
and save into the artifact scratch.
"""

from __future__ import annotations

VL = "vega_lite"
PY = "python"

RECIPES: dict[str, dict] = {
    "line": {
        "kind": VL,
        "for": "trends over a continuous x (time, cycles, load)",
        "template": {
            "mark": "line",
            "encoding": {
                "x": {"field": "time", "type": "quantitative"},
                "y": {"field": "value", "type": "quantitative"},
                "color": {"field": "series", "type": "nominal"},
            },
        },
    },
    "scatter": {
        "kind": VL,
        "for": "relationships between two measures; add a size/color channel for a third",
        "template": {
            "mark": {"type": "point", "filled": True},
            "encoding": {
                "x": {"field": "x", "type": "quantitative"},
                "y": {"field": "y", "type": "quantitative"},
                "tooltip": [{"field": "x"}, {"field": "y"}],
            },
        },
    },
    "bar": {
        "kind": VL,
        "for": "comparisons across categories",
        "template": {
            "mark": "bar",
            "encoding": {
                "x": {"field": "category", "type": "nominal", "sort": "-y"},
                "y": {"field": "value", "type": "quantitative"},
            },
        },
    },
    "histogram": {
        "kind": VL,
        "for": "distribution of one measure",
        "template": {
            "mark": "bar",
            "encoding": {
                "x": {"field": "value", "type": "quantitative", "bin": {"maxbins": 40}},
                "y": {"aggregate": "count"},
            },
        },
    },
    "cdf": {
        "kind": VL,
        "for": "cumulative distribution — yield/percentile questions",
        "template": {
            "transform": [
                {"sort": [{"field": "value"}], "window": [{"op": "cume_dist", "as": "cdf"}]},
            ],
            "mark": "line",
            "encoding": {
                "x": {"field": "value", "type": "quantitative"},
                "y": {"field": "cdf", "type": "quantitative", "axis": {"format": ".0%"}},
            },
        },
    },
    "log_axes": {
        "kind": VL,
        "for": "quantities spanning decades — set scale type log on the axis",
        "template": {
            "mark": "line",
            "encoding": {
                "x": {"field": "frequency", "type": "quantitative", "scale": {"type": "log"}},
                "y": {"field": "magnitude", "type": "quantitative"},
            },
        },
    },
    "error_bars": {
        "kind": VL,
        "for": "measurements with uncertainty — layer errorbar over points",
        "template": {
            "layer": [
                {
                    "mark": "errorbar",
                    "encoding": {
                        "x": {"field": "condition", "type": "nominal"},
                        "y": {"field": "lo", "type": "quantitative", "title": "value"},
                        "y2": {"field": "hi"},
                    },
                },
                {
                    "mark": {"type": "point", "filled": True},
                    "encoding": {
                        "x": {"field": "condition", "type": "nominal"},
                        "y": {"field": "mean", "type": "quantitative"},
                    },
                },
            ],
        },
    },
    "tolerance_band": {
        "kind": VL,
        "for": "a measurement against spec limits — band behind the trace",
        "template": {
            "layer": [
                {
                    "mark": {"type": "area", "opacity": 0.15},
                    "encoding": {
                        "x": {"field": "x", "type": "quantitative"},
                        "y": {"field": "lower_spec", "type": "quantitative"},
                        "y2": {"field": "upper_spec"},
                    },
                },
                {
                    "mark": "line",
                    "encoding": {
                        "x": {"field": "x", "type": "quantitative"},
                        "y": {"field": "measured", "type": "quantitative"},
                    },
                },
            ],
        },
    },
    "control_chart": {
        "kind": VL,
        "for": "SPC: individuals chart with center line and ±3σ limits (compute the limits in the kernel first)",
        "template": {
            "layer": [
                {"mark": "line", "encoding": {
                    "x": {"field": "sample", "type": "quantitative"},
                    "y": {"field": "value", "type": "quantitative"}}},
                {"mark": {"type": "rule", "strokeDash": [4, 4]}, "encoding": {
                    "y": {"field": "ucl", "type": "quantitative"}}},
                {"mark": {"type": "rule", "strokeDash": [4, 4]}, "encoding": {
                    "y": {"field": "lcl", "type": "quantitative"}}},
            ],
        },
    },
    "heatmap": {
        "kind": VL,
        "for": "a measure over two categories / a coarse 2D field",
        "template": {
            "mark": "rect",
            "encoding": {
                "x": {"field": "col", "type": "ordinal"},
                "y": {"field": "row", "type": "ordinal"},
                "color": {"field": "value", "type": "quantitative"},
            },
        },
    },
    "bode": {
        "kind": PY,
        "for": "frequency response magnitude+phase from a transfer function",
        "template": (
            "import numpy as np\n"
            "from scipy import signal\n"
            "import matplotlib.pyplot as plt\n"
            "system = signal.TransferFunction([1], [1, 1])  # H(s) = 1/(s+1)\n"
            "w, mag, phase = signal.bode(system)\n"
            "fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(8, 6))\n"
            "ax1.semilogx(w, mag); ax1.set_ylabel('Magnitude [dB]'); ax1.grid(True)\n"
            "ax2.semilogx(w, phase); ax2.set_ylabel('Phase [deg]')\n"
            "ax2.set_xlabel('ω [rad/s]'); ax2.grid(True)\n"
            "fig.savefig(OUT, dpi=150)  # OUT = an absolute path in the artifact scratch\n"
        ),
    },
    "fft": {
        "kind": PY,
        "for": "spectrum of a sampled signal",
        "template": (
            "import numpy as np\n"
            "import matplotlib.pyplot as plt\n"
            "y = DATA['signal']['value'].to_numpy()  # a loaded frame\n"
            "fs = 1000.0  # sample rate [Hz]\n"
            "freq = np.fft.rfftfreq(len(y), 1 / fs)\n"
            "amp = np.abs(np.fft.rfft(y)) * 2 / len(y)\n"
            "fig, ax = plt.subplots(figsize=(8, 4))\n"
            "ax.semilogy(freq, amp); ax.set_xlabel('Hz'); ax.set_ylabel('amplitude')\n"
            "ax.grid(True); fig.savefig(OUT, dpi=150)\n"
        ),
    },
    "contour": {
        "kind": PY,
        "for": "a dense 2D field (stress map, response surface)",
        "template": (
            "import numpy as np\n"
            "import matplotlib.pyplot as plt\n"
            "x = np.linspace(-2, 2, 200); y = np.linspace(-2, 2, 200)\n"
            "X, Y = np.meshgrid(x, y); Z = np.exp(-(X**2 + Y**2))\n"
            "fig, ax = plt.subplots(figsize=(6, 5))\n"
            "cs = ax.contourf(X, Y, Z, levels=20)\n"
            "fig.colorbar(cs); fig.savefig(OUT, dpi=150)\n"
        ),
    },
}


def viz_recipes(topic: str = "") -> dict:
    if not topic:
        return {
            "topics": {
                name: recipe["for"] for name, recipe in sorted(RECIPES.items())
            },
            "note": (
                "Ask again with a topic for the template. vega_lite recipes go "
                "straight into chart_spec; python recipes run via py_run (set "
                "OUT to an absolute path in the artifact scratch first)."
            ),
        }
    recipe = RECIPES.get(topic)
    if recipe is None:
        raise ValueError(f"no recipe {topic!r} — topics: {sorted(RECIPES)}")
    return {"topic": topic, **recipe}
