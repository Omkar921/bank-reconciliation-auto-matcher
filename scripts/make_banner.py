"""Render the README banner (docs/images/banner.png) with matplotlib."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

W, H = 16, 4.5
fig = plt.figure(figsize=(W, H), dpi=150)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")
grad = np.linspace(0, 1, 512).reshape(1, -1)
ax.imshow(grad, extent=[0, W, 0, H], cmap=matplotlib.colors.LinearSegmentedColormap.from_list("g", ["#0F2338", "#1F3A5F", "#22577A"]), aspect="auto")
for x in np.arange(0, W, 0.5):  # faint ledger grid
    ax.plot([x, x], [0, H], color="white", alpha=0.03, lw=0.8)
for y in np.arange(0, H, 0.35):
    ax.plot([0, W], [y, y], color="white", alpha=0.03, lw=0.8)

ax.text(0.8, 2.75, "Bank Reconciliation Auto-Matcher", color="white", fontsize=38, fontweight="bold", va="center")
ax.text(0.82, 1.95, "Month-end bank-to-GL matching  ·  exact & fuzzy rules  ·  exception review queue",
        color="#CFE3F2", fontsize=16, va="center")
for i, (label, col) in enumerate([("Python", "#2A9D8F"), ("pandas", "#2A9D8F"), ("rapidfuzz", "#E9C46A"),
                                  ("openpyxl", "#2A9D8F"), ("Streamlit", "#E76F51")]):
    x = 0.82 + i * 1.55
    ax.add_patch(FancyBboxPatch((x, 0.85), 1.35, 0.42, boxstyle="round,pad=0.02,rounding_size=0.18",
                                fc=col, ec="none", alpha=0.95))
    ax.text(x + 0.675, 1.06, label, ha="center", va="center", fontsize=12, color="#0F2338", fontweight="bold")

# Right-hand "ledger" illustration: bank lines linked to GL lines
bx, gx, y0 = 11.6, 14.2, 3.7
rows = [("Exact", "#2A9D8F"), ("Strong", "#2A9D8F"), ("Suggested", "#E9C46A"), ("Exact", "#2A9D8F"), (None, "#E76F51"), ("Strong", "#2A9D8F")]
ax.text(bx + 0.6, 4.1, "BANK", color="#CFE3F2", ha="center", fontsize=11, fontweight="bold")
ax.text(gx + 0.6, 4.1, "LEDGER", color="#CFE3F2", ha="center", fontsize=11, fontweight="bold")
for i, (rule, col) in enumerate(rows):
    y = y0 - i * 0.55
    for x in (bx, gx):
        ax.add_patch(FancyBboxPatch((x, y - 0.17), 1.2, 0.34, boxstyle="round,pad=0.01,rounding_size=0.08",
                                    fc="white", ec="none", alpha=0.14))
        ax.plot([x + 0.12, x + 0.8], [y, y], color="white", alpha=0.55, lw=2.2)
    if rule:
        ax.plot([bx + 1.22, gx - 0.02], [y, y], color=col, lw=2.2, ls="-" if rule != "Suggested" else "--")
        ax.text((bx + gx + 1.2) / 2, y + 0.08, rule, color=col, fontsize=8.5, ha="center", va="bottom")
    else:
        ax.text((bx + gx + 1.2) / 2, y, "✕ exception", color=col, fontsize=9, ha="center", va="center", fontweight="bold")
fig.savefig("docs/images/banner.png", dpi=150)
