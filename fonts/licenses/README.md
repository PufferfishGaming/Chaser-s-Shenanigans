# Bundled font licences

Every font shipped in `fonts/` is redistributable. The licence text for each
family sits next to this file.

| File in `fonts/` | Family | Licence |
|---|---|---|
| `Roboto-Regular.ttf`, `Roboto-Medium.ttf`, `Roboto-Bold.ttf` | Roboto | `Roboto-LICENSE.txt` |
| `EBGaramond-VF.ttf` | EB Garamond | `EBGaramond-OFL.txt` |
| `CormorantGaramond-VF.ttf` | Cormorant Garamond | `CormorantGaramond-OFL.txt` |
| `LibreBaskerville-VF.ttf` | Libre Baskerville | `LibreBaskerville-OFL.txt` |
| `Lora-VF.ttf` | Lora | `Lora-OFL.txt` |
| `DancingScript-VF.ttf` | Dancing Script | `DancingScript-OFL.txt` |
| `GreatVibes-Regular.ttf` | Great Vibes | `GreatVibes-OFL.txt` |
| `Parisienne-Regular.ttf` | Parisienne | `Parisienne-OFL.txt` |

Notes:

- The `-VF` files are **unmodified upstream variable fonts** with a `wght` axis.
  They are shipped exactly as published; weights are selected at render time via
  `ImageFont.set_variation_by_name()`. Nothing is instanced, subset or renamed,
  so the OFL Reserved Font Name clause is not engaged.
- The bundled Roboto statics were inherited from the upstream
  [photoborder](https://github.com/stevequinn/photoborder) project and predate
  Google's relicensing of Roboto from Apache-2.0 to OFL-1.1. Both licences
  permit redistribution; `Roboto-LICENSE.txt` holds the current upstream text.
- Renaming a font *file* (e.g. `EBGaramond[wght].ttf` -> `EBGaramond-VF.ttf`)
  does not alter the font's internal name table and is not a modification. The
  brackets were dropped because they are awkward to quote across `.bat`, `.sh`
  and zip tooling.
