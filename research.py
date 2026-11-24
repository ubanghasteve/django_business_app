"""
Figure 5: Cellular Composition and Intratumoral Heterogeneity of the Tumor Microenvironment
================================================================================================
A comprehensive multi-panel visualization of TME analysis.
Publication-ready format with SVG, PDF, and PNG export.
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle
from matplotlib.gridspec import GridSpec
from matplotlib.patches import FancyBboxPatch, Rectangle, Polygon, FancyArrowPatch
from matplotlib.collections import PatchCollection, LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
import textwrap

np.random.seed(42)

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.titlesize"] = 11
plt.rcParams["axes.labelsize"] = 9
plt.rcParams["xtick.labelsize"] = 8
plt.rcParams["ytick.labelsize"] = 8
plt.rcParams["legend.fontsize"] = 7.5

COLORS = {
    "ink": "#1a1a2e",
    "panel_bg": "#fdfcff",
    "panel_border": "#c8d0e0",
    "title_bg": "#eef2f8",
    "annot_bg": "#fffffe",
    "annot_border": "#d4d0c8",
}

CELL_COLORS = {
    "Malignant": "#e63946",
    "TAM": "#457b9d",
    "CTL": "#2a9d8f",
    "Treg": "#9b59b6",
    "CAF": "#f4a261",
    "Endothelial": "#264653",
}

CLUSTER_COLORS = ["#e63946", "#457b9d", "#2a9d8f", "#9b59b6", "#f4a261", "#264653"]

def style_panel(ax, letter, title):
    """Apply consistent panel styling."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_facecolor(COLORS["panel_bg"])

    outer = FancyBboxPatch(
        (0.005, 0.01), 0.99, 0.98,
        boxstyle="round,pad=0.005,rounding_size=0.012",
        linewidth=1.5, edgecolor=COLORS["panel_border"],
        facecolor=COLORS["panel_bg"], transform=ax.transAxes, clip_on=False, zorder=1
    )
    ax.add_patch(outer)
    
    ax.add_patch(Rectangle((0.005, 0.895), 0.99, 0.1, 
                           color=COLORS["title_bg"], ec="none", transform=ax.transAxes, zorder=2))
    
    ax.text(0.02, 0.94, f"({letter})", fontsize=12, fontweight="bold",
            va="center", ha="left", color=COLORS["ink"], transform=ax.transAxes, zorder=3)
    ax.text(0.09, 0.94, title, fontsize=10, fontweight="bold",
            va="center", ha="left", color=COLORS["ink"], transform=ax.transAxes, zorder=3)


def annotation_box(ax, x, y, w, h, title, lines, fc=None, ec=None, fontsize=7.5):
    """Enhanced annotation box."""
    if fc is None:
        fc = COLORS["annot_bg"]
    if ec is None:
        ec = COLORS["annot_border"]
        
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.01,rounding_size=0.01",
        linewidth=0.8, edgecolor=ec, facecolor=fc,
        transform=ax.transAxes, zorder=6
    )
    ax.add_patch(box)
    
    ax.text(x + 0.02, y + h - 0.035, title,
            fontsize=fontsize, fontweight="bold", va="top", ha="left",
            color=COLORS["ink"], transform=ax.transAxes, zorder=7)
    
    max_chars = max(12, int(55 * w))
    wrapped_lines = []
    for line in lines:
        if line.startswith("•"):
            wrapped_lines.append(line)
        else:
            pieces = textwrap.wrap(line, width=max_chars) or [line]
            for i, piece in enumerate(pieces):
                wrapped_lines.append(("• " if i == 0 else "  ") + piece)
    
    text_top = y + h - 0.065
    text_bottom = y + 0.025
    available_h = max(0.01, text_top - text_bottom)
    n_lines = max(1, len(wrapped_lines))
    step = min(available_h / n_lines, 0.045)
    line_fontsize = min(fontsize, max(6.0, 200 * step))
    
    yy = text_top
    for line in wrapped_lines:
        ax.text(x + 0.025, yy, line, fontsize=line_fontsize, va="top", ha="left",
                color=COLORS["ink"], transform=ax.transAxes, zorder=7)
        yy -= step


def build_figure():
    fig = plt.figure(figsize=(20, 22), dpi=300)
    gs = GridSpec(3, 3, figure=fig, hspace=0.13, wspace=0.11,
                  left=0.03, right=0.97, top=0.96, bottom=0.02)
    
    n_cells = [280, 200, 180, 140, 120, 110, 90, 80]
    centers = np.array([
        [-3.5, 2.0], [2.0, 2.5], [-2.0, -1.5], [3.0, -1.0],
        [0.0, 3.5], [-3.0, -3.0], [1.5, -3.5], [-1.5, 0.5]
    ])
    pts_all, labels = [], []
    for i, (cx, cy) in enumerate(centers):
        angle = np.random.uniform(0, 2*np.pi)
        scale = 0.3 + 0.15 * np.random.rand()
        cov = np.array([
            [scale * np.cos(angle)**2 + 0.2, 0.1 * np.sin(2*angle)],
            [0.1 * np.sin(2*angle), scale * np.sin(angle)**2 + 0.2]
        ])
        cov = cov @ cov.T + 0.1 * np.eye(2)
        p = np.random.multivariate_normal(mean=[cx, cy], cov=cov, size=n_cells[i])
        pts_all.append(p)
        labels.extend([i] * n_cells[i])
    embedding = np.vstack(pts_all)
    labels = np.array(labels)
    
    samples = ["T1", "T2", "T3", "T4", "T5", "T6"]

    axA = fig.add_subplot(gs[0, 0])
    style_panel(axA, "A", "UMAP Visualization of Cell Populations")
    
    chartA = axA.inset_axes((0.06, 0.12, 0.65, 0.72))
    
    scatter_colors = [CLUSTER_COLORS[l % len(CLUSTER_COLORS)] for l in labels]
    chartA.scatter(embedding[:, 0], embedding[:, 1], c=scatter_colors, s=15, 
                   alpha=0.85, linewidths=0.2, edgecolors="white")
    chartA.set_xlabel("UMAP-1", fontsize=9, style="italic")
    chartA.set_ylabel("UMAP-2", fontsize=9, style="italic")
    chartA.grid(alpha=0.15)
    for s in ["top", "right"]:
        chartA.spines[s].set_visible(False)
    
    cell_types = [
        "Malignant epithelial",
        "Tumor-assoc. macrophages",
        "Cytotoxic T lymphocytes",
        "Regulatory T cells",
        "Cancer-assoc. fibroblasts",
        "Endothelial cells",
    ]
    legend_items = []
    for i, ct in enumerate(cell_types):
        legend_items.append(plt.Line2D([0], [0], marker='o', color='w', 
                                        markerfacecolor=CLUSTER_COLORS[i], 
                                        markersize=8, label=ct))
    chartA.legend(handles=legend_items, loc="upper left", fontsize=6.5, 
                   frameon=True, framealpha=0.9, edgecolor="gray")
    
    annotation_box(axA, 0.72, 0.12, 0.26, 0.72,
        "Identified Cell Populations",
        ["Malignant epithelial cells",
         "Tumor-assoc. macrophages",
         "Cytotoxic T lymphocytes",
         "Regulatory T cells",
         "Cancer-assoc. fibroblasts",
         "Endothelial cells"],
        fc="#f8f9fa", ec="#b8c4d8"
    )
    
    axA.text(0.06, 0.06, "Reveals transcriptional heterogeneity within TME",
             fontsize=7, color="#555", style="italic", transform=axA.transAxes)

    axB = fig.add_subplot(gs[0, 1])
    style_panel(axB, "B", "Heatmap of Marker Gene Expression")
    
    chartB = axB.inset_axes((0.08, 0.16, 0.55, 0.66))
    
    marker_genes = ["EPCAM", "KRT18", "CD3D", "CD8A", "FOXP3", "CD68", 
                   "CD163", "COL1A1", "FAP", "PECAM1", "VWF", "CD34"]
    cell_clusters = ["Malignant", "TAM", "CTL", "Treg", "CAF", "Endo"]
    
    heat_data = np.zeros((len(marker_genes), len(cell_clusters)))
    for i, gene in enumerate(marker_genes):
        peaks = {"EPCAM": 0, "KRT18": 0, "CD3D": 2, "CD8A": 2, "FOXP3": 3,
                 "CD68": 1, "CD163": 1, "COL1A1": 4, "FAP": 4, 
                 "PECAM1": 5, "VWF": 5, "CD34": 5}
        peak_c = peaks.get(gene, i % 6)
        heat_data[i, :] = np.random.normal(0.2, 0.3, 6)
        heat_data[i, peak_c] = np.random.uniform(2.0, 2.8)
    
    cmap = LinearSegmentedColormap.from_list("expr", ["#2166ac", "#f7f7f7", "#b2182b"])
    im = chartB.imshow(heat_data, cmap=cmap, aspect="auto", vmin=-1.5, vmax=2.5)
    
    chartB.set_xticks(range(len(cell_clusters)))
    chartB.set_xticklabels(cell_clusters, fontsize=8, rotation=30, ha="right")
    chartB.set_yticks(range(len(marker_genes)))
    chartB.set_yticklabels(marker_genes, fontsize=8)
    chartB.set_xlabel("Cell Clusters", fontsize=9, style="italic")
    
    cax = axB.inset_axes((0.65, 0.16, 0.035, 0.66))
    cb = fig.colorbar(im, cax=cax)
    cb.ax.tick_params(labelsize=7)
    cb.set_label("Expression (Z-score)", fontsize=7.5)
    
    annotation_box(axB, 0.70, 0.16, 0.27, 0.66,
        "Annotation",
        ["High expression (red) indicates",
         "cell-type-specific signatures",
         "used for cluster annotation"],
        fc="#f8f9fa", ec="#b8c4d8"
    )

    axC = fig.add_subplot(gs[0, 2])
    style_panel(axC, "C", "Cluster Composition Across Samples")
    
    chartC = axC.inset_axes((0.08, 0.18, 0.64, 0.64))
    
    xpos = np.arange(len(samples))
    bottom = np.zeros(len(samples))
    
    proportions = {
        0: [0.32, 0.28, 0.35, 0.30, 0.33, 0.27],
        1: [0.22, 0.25, 0.18, 0.24, 0.20, 0.23],
        2: [0.18, 0.15, 0.20, 0.16, 0.18, 0.20],
        3: [0.08, 0.10, 0.07, 0.09, 0.08, 0.10],
        4: [0.12, 0.14, 0.12, 0.13, 0.13, 0.12],
        5: [0.08, 0.08, 0.08, 0.08, 0.08, 0.08],
    }
    
    for i in range(6):
        vals = np.array(proportions[i]) * 100
        bars = chartC.bar(xpos, vals, bottom=bottom, color=CLUSTER_COLORS[i], 
                         edgecolor="white", linewidth=0.6, width=0.65)
        bottom += vals
    
    chartC.set_xticks(xpos)
    chartC.set_xticklabels(samples, fontsize=9)
    chartC.set_ylim(0, 100)
    chartC.set_ylabel("Cell Proportion (%)", fontsize=9, style="italic")
    chartC.set_xlabel("Tumor Samples", fontsize=9, style="italic")
    chartC.grid(axis="y", alpha=0.2)
    for s in ["top", "right"]:
        chartC.spines[s].set_visible(False)
    
    annotation_box(axC, 0.75, 0.18, 0.22, 0.64,
        "Inter-Sample",
        ["Heterogeneity",
         "Variation indicates",
         "differences in immune",
         "infiltration and stromal",
         "composition"],
        fc="#f8f9fa", ec="#b8c4d8"
    )

    axD = fig.add_subplot(gs[1, 0])
    style_panel(axD, "D", "Immune Cell Infiltration Analysis")
    
    chartD = axD.inset_axes((0.06, 0.15, 0.58, 0.70))
    
    x = np.arange(len(samples))
    width = 0.35
    
    macro_vals = [45, 52, 38, 48, 42, 55]
    tcell_vals = [32, 28, 38, 30, 35, 25]
    
    bars1 = chartD.bar(x - width/2, macro_vals, width, label="Macrophages", 
                       color="#457b9d", edgecolor="white", linewidth=0.5)
    bars2 = chartD.bar(x + width/2, tcell_vals, width, label="T lymphocytes", 
                       color="#2a9d8f", edgecolor="white", linewidth=0.5)
    
    chartD.set_xticks(x)
    chartD.set_xticklabels(samples, fontsize=9)
    chartD.set_ylabel("Infiltration Score", fontsize=9, style="italic")
    chartD.set_xlabel("Tumor Samples", fontsize=9, style="italic")
    chartD.legend(loc="upper right", fontsize=8, frameon=True, edgecolor="gray")
    chartD.grid(axis="y", alpha=0.2)
    for s in ["top", "right"]:
        chartD.spines[s].set_visible(False)
    
    annotation_box(axD, 0.68, 0.15, 0.29, 0.70,
        "Immune Engagement",
        ["Active presence of",
         "macrophages and T cells",
         "indicates immune response",
         "and suppression dynamics"],
        fc="#f8f9fa", ec="#b8c4d8"
    )

    axE = fig.add_subplot(gs[1, 1])
    style_panel(axE, "E", "Fibroblast Activation Signature")
    
    chartE = axE.inset_axes((0.08, 0.16, 0.55, 0.70))
    
    caf_genes = ["COL1A1", "COL3A1", "FN1", "FAP", "ACTA2", "TAGLN", "MMP2", "MMP9"]
    normal_c = [0.8, 0.6, 0.7, 0.3, 0.5, 0.4, 0.4, 0.3]
    activated_c = [3.2, 2.8, 3.5, 2.2, 2.8, 2.5, 2.0, 1.8]
    
    x = np.arange(len(caf_genes))
    chartE.barh(x + 0.2, activated_c, height=0.35, color="#f4a261", 
               edgecolor="white", linewidth=0.5, label="Activated CAFs")
    chartE.barh(x - 0.2, normal_c, height=0.35, color="#ffd4a8", 
               edgecolor="white", linewidth=0.5, label="Normal Fibroblasts")
    
    chartE.set_yticks(x)
    chartE.set_yticklabels(caf_genes, fontsize=8)
    chartE.set_xlabel("Expression Level", fontsize=9, style="italic")
    chartE.legend(loc="lower right", fontsize=7.5, frameon=True, edgecolor="gray")
    chartE.grid(axis="x", alpha=0.2)
    for s in ["top", "right"]:
        chartE.spines[s].set_visible(False)
    
    annotation_box(axE, 0.68, 0.16, 0.29, 0.70,
        "CAF Activity",
        ["ECM gene expression:",
         "COL1A1, FN1, FAP",
         "Promotes tumor progression",
         "through stromal remodeling"],
        fc="#f8f9fa", ec="#b8c4d8"
    )

    axF = fig.add_subplot(gs[1, 2])
    style_panel(axF, "F", "Endothelial Cell Angiogenic Signature")
    
    chartF = axF.inset_axes((0.06, 0.14, 0.60, 0.72))
    
    angio_genes = ["VEGFA", "VEGFR2", "PECAM1", "CDH5", "ANGPT2", "KDR", "FLT1"]
    
    angles = np.linspace(0, 2*np.pi, len(angio_genes), endpoint=False)
    angles = np.append(angles, angles[0])
    
    base_vals = np.array([3.5, 2.8, 4.2, 3.0, 2.5, 3.2, 2.8])
    base_vals = np.append(base_vals, base_vals[0])
    
    chartF.fill(angles, base_vals, alpha=0.3, color="#264653")
    chartF.plot(angles, base_vals, 'o-', color="#264653", linewidth=2, markersize=8)
    
    chartF.set_xticks(angles[:-1])
    chartF.set_xticklabels(angio_genes, fontsize=8)
    chartF.set_ylim(0, 5)
    chartF.set_ylabel("Expression Level", fontsize=9, style="italic")
    chartF.set_title("Angiogenic Gene Expression", fontsize=9, style="italic", pad=10)
    
    annotation_box(axF, 0.70, 0.14, 0.27, 0.72,
        "Angiogenic Activity",
        ["VEGF signaling pathway",
         "Vascular development",
         "Supports tumor growth",
         "and metastasis"],
        fc="#f8f9fa", ec="#b8c4d8"
    )

    axG = fig.add_subplot(gs[2, 0])
    style_panel(axG, "G", "Stromal Interaction Network")
    
    chartG = axG.inset_axes((0.05, 0.12, 0.65, 0.80))
    chartG.set_xlim(-1.5, 1.5)
    chartG.set_ylim(-1.5, 1.5)
    
    nodes = {
        "Tumor": (0, 0.8, "#e63946", "Tumor\nCells"),
        "CAF": (-0.9, 0.2, "#f4a261", "CAFs"),
        "Endo": (0.9, 0.2, "#264653", "Endothelial\nCells"),
        "TAM": (-0.6, -0.7, "#457b9d", "TAMs"),
        "CTL": (0.6, -0.7, "#2a9d8f", "CTLs"),
    }
    
    edges = [
        ("CAF", "Tumor", 0.8, "#f4a261"),
        ("Endo", "Tumor", 0.9, "#264653"),
        ("TAM", "Tumor", 0.7, "#457b9d"),
        ("CAF", "Endo", 0.6, "#f4a261"),
        ("TAM", "CTL", 0.5, "#9b59b6"),
        ("Tumor", "CTL", 0.4, "#e63946"),
    ]
    
    for e1, e2, weight, color in edges:
        x1, y1, _, _ = nodes[e1]
        x2, y2, _, _ = nodes[e2]
        chartG.annotate("", xy=(x2, y2), xytext=(x1, y1),
                       arrowprops=dict(arrowstyle="->", color=color, 
                                      lw=1.5*weight, alpha=0.7))
    
    for name, (x, y, color, label) in nodes.items():
        circle = plt.Circle((x, y), 0.22, color=color, ec="white", linewidth=2, zorder=5)
        chartG.add_patch(circle)
        chartG.text(x, y, label, ha="center", va="center", fontsize=7, 
                   fontweight="bold", color="white", zorder=6)
    
    chartG.axis("off")
    
    annotation_box(axG, 0.73, 0.12, 0.24, 0.80,
        "Cellular Cross-talk",
        ["Fibroblast-tumor axis",
         "Endothelial support",
         "Immune cell signaling",
         "Communication networks"],
        fc="#f8f9fa", ec="#b8c4d8"
    )

    axH = fig.add_subplot(gs[2, 1])
    style_panel(axH, "H", "Immune Activation & Suppression")
    
    chartH = axH.inset_axes((0.06, 0.14, 0.60, 0.72))
    
    x = np.arange(len(samples))
    width = 0.35
    
    activation = [0.65, 0.58, 0.72, 0.62, 0.68, 0.55]
    suppression = [0.35, 0.42, 0.28, 0.38, 0.32, 0.45]
    
    bars1 = chartH.bar(x - width/2, activation, width, label="Cytotoxic Activity", 
                       color="#2a9d8f", edgecolor="white", linewidth=0.5)
    bars2 = chartH.bar(x + width/2, suppression, width, label="Treg Suppression", 
                       color="#9b59b6", edgecolor="white", linewidth=0.5)
    
    for bar, val in zip(bars1, activation):
        chartH.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                   f'{val:.2f}', ha='center', va='bottom', fontsize=7)
    for bar, val in zip(bars2, suppression):
        chartH.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                   f'{val:.2f}', ha='center', va='bottom', fontsize=7)
    
    chartH.axhline(y=0.5, color="gray", linestyle="--", alpha=0.5, linewidth=1)
    chartH.text(len(samples)-0.5, 0.52, "Balance Line", fontsize=7, color="gray")
    
    chartH.set_xticks(x)
    chartH.set_xticklabels(samples, fontsize=9)
    chartH.set_ylabel("Activity Score", fontsize=9, style="italic")
    chartH.set_xlabel("Tumor Samples", fontsize=9, style="italic")
    chartH.set_ylim(0, 1)
    chartH.legend(loc="upper right", fontsize=8, frameon=True, edgecolor="gray")
    chartH.grid(axis="y", alpha=0.2)
    for s in ["top", "right"]:
        chartH.spines[s].set_visible(False)
    
    annotation_box(axH, 0.70, 0.14, 0.27, 0.72,
        "Immune Balance",
        ["Activation vs suppression",
         "determines tumor response",
         "CTL: tumor killing",
         "Treg: immune dampening"],
        fc="#f8f9fa", ec="#b8c4d8"
    )

    axI = fig.add_subplot(gs[2, 2])
    style_panel(axI, "I", "Spatial Organization & Cell Interactions")
    
    chartI = axI.inset_axes((0.06, 0.14, 0.60, 0.72))
    
    chartI.set_xlim(-1.2, 1.2)
    chartI.set_ylim(-1.2, 1.2)
    
    grid_x, grid_y = np.meshgrid(np.linspace(-1, 1, 7), np.linspace(-1, 1, 7))
    
    spatial_assign = np.array([
        [0, 0, 4, 4, 4, 5, 5],
        [0, 0, 4, 2, 4, 5, 5],
        [1, 1, 4, 2, 4, 3, 5],
        [1, 1, 2, 2, 2, 3, 3],
        [1, 1, 2, 2, 3, 3, 5],
        [0, 0, 1, 1, 3, 5, 5],
        [0, 0, 1, 1, 5, 5, 5],
    ])
    
    for i in range(7):
        for j in range(7):
            x, y = grid_x[i, j], grid_y[i, j]
            circle = plt.Circle((x, y), 0.10, color=CLUSTER_COLORS[spatial_assign[i, j]], 
                               ec="white", linewidth=0.5, alpha=0.9)
            chartI.add_patch(circle)
    
    region_labels = [
        ("Tumor Core", -0.5, 0, "#e63946"),
        ("Immune\nInfiltrate", 0.35, -0.5, "#2a9d8f"),
        ("Stromal\nBorder", -0.65, 0.6, "#f4a261"),
    ]
    
    for text, x, y, color in region_labels:
        chartI.text(x, y, text, ha='center', va='center', fontsize=8, 
                   fontweight='bold', color=color,
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                            edgecolor=color, alpha=0.8))
    
    chartI.axis("off")
    
    annotation_box(axI, 0.70, 0.14, 0.27, 0.72,
        "Spatial Context",
        ["Inferred from similarity",
         "Tumor-immune boundaries",
         "CAF distribution patterns",
         "Vascular proximity"],
        fc="#f8f9fa", ec="#b8c4d8"
    )

    fig.suptitle("Figure 5. Cellular Composition and Intratumoral Heterogeneity\nof the Tumor Microenvironment",
                 fontsize=18, fontweight="bold", y=0.995, color="#1a1a2e")

    fig.savefig("figure5_tumor_microenvironment.svg", format="svg", bbox_inches="tight", dpi=300)
    fig.savefig("figure5_tumor_microenvironment.pdf", bbox_inches="tight", dpi=300)
    fig.savefig("figure5_tumor_microenvironment.png", format="png", dpi=300, bbox_inches="tight")
    
    plt.close(fig)
    
    print("=" * 70)
    print("Figure 5 Export Complete!")
    print("=" * 70)
    print("Files generated:")
    print("  • figure5_tumor_microenvironment.svg  (Editable vector - CorelDRAW)")
    print("  • figure5_tumor_microenvironment.pdf  (Print quality)")
    print("  • figure5_tumor_microenvironment.png  (Preview @ 300 DPI)")
    print("=" * 70)


if __name__ == "__main__":
    build_figure()
