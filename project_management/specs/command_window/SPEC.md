# Command Window Specification

## 22_command_window.png
![Command Window](22_command_window.png)
- What it shows: Command window/terminal with IPython prompt, command history dropdown, and clear button.
- **Divergence from Igor Pro Image**: 
  - There should NOT be a separate text-entry widget at the bottom. The behavior must emulate standard rich IPython (just like the Spyder IDE).
  - IPython syntax highlighting is strictly expected.
  - Standard IPython prompt structures (`In`/`Out`) are expected instead of Igor Pro log numbering:
    ```
    In [1]: 1+1
    Out[1]: 2

    In [2]: 
    ```
