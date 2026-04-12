# Figure Window Specification

## 01_graph_construction.png
![Figure Window](01_graph_construction.png)
- What it shows: An active matplotlib figure living as a native MDI child window (visible beneath the new curve dialog).
- Hyde specific behavior: The figure is rendered natively in the GUI process (via a custom matplotlib backend inside the MDI area) but serves purely as a viewport driven by the underlying IPython `spyder_kernels` instance.
  - **Rigorous Implementation Detail**: The communication of graphical output must be achieved by developing a dedicated, custom `matplotlib` backend. You must not attempt to monkey-patch an existing backend. This provides the clean foundation necessary for future interactivity (such as user-placeable graph cursors or spawning contingent dialogs right from figure clicks).

## 04_graph_close_save_script.png
![Save Script Prompt](04_graph_close_save_script.png)
- What it shows: the close-window prompt asking whether to save the figure recreation script.
- Igor features: save-on-close figure scripts, naming the saved script, and save/discard choices.

## 05_saved_graph_menu.png
![Saved Graph Menu](05_saved_graph_menu.png)
- What it shows: a saved figure appearing in the window/menu hierarchy.
- Igor features: persistent menu registry for saved figures/scripts and reopen-by-name behavior.
