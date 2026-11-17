# Gambling Lord (賭霸) — Complete Text Inventory & ROM Map

All Traditional Chinese text in `Gambling Lord (Taiwan).bin` (Super A'Can, Funtech 1995/1996, `2,097,152` bytes / `0x200000`, 16-bit byte-swapped) is stored as pre-rendered 4bpp tilemaps and sprite banks (both `d222`-compressed and raw uncompressed). No dynamic text encoding table exists.

| # | Area | CPU Address Range | Format | Max Tiles / Sprites | Notes |
|---|---|---|---|---|---|
| 1 | Title Mode Banner | `0x09FE2E..0x0A7D50` | Uncompressed `27x3` map + `1,012` tiles | `1,012` tiles (`71` banner tiles used) | Scrolls at bottom of Title Screen (`pal=11`, bg `13`) |
| 2 | Imperial Edict | `0x08E294..0x0908D2`, `0x090BBA..0x0913BA` | `0xF3` tiles (`830`) + raw `32x32` map | `830` tiles (`0..648` scenery protected) | Vertical decree text inside scroll frame (`pal=14`, bg `7`, ink `6`) |
| 3 | Character Select Headers | `0x095018..0x095146`, `0x095146..0x0953FE` | `0xF4` `64x32` map + `0xF4` `66` tiles | `66` tiles (`1..36` headers, `37..65` frames) | 4 column headers (`PLAYER`, `RIVAL` x3) |
| 4 | Character Select Nameplates | `0x0936F8..0x093C98`, `0x093C98..0x095018` | `720`-word map + `0xF3` `395` tiles | `395` tiles (`0..334` plaques, `335..394` reticle/orb) | 16 `8x3` wood-framed nameplates across `CS Pal 4` & `CS Pal 8` (`0x0285DA` table) |
| 5 | VS Intro Screen | `0x0953FE..0x095770`, `0x095770..0x09580A`, `0x09580A..0x09743F` | `0xF3` `64x32` map + 7 `3x3` overlays + `0xF3` `512` tiles | `512` tiles | 5 diamonds `RND 1..7 SET` (`pal=3`) + center `GAMBLING LORD` crest (`pal=2`) |
| 6 | Tournament Bracket | `0x097654..0x097B8A`, `0x09A9AC..0x09AEC8`, `0x097B8A..0x09A9AC` | Two `0xF3` `64x64` maps sharing `0xF3` `875` tiles | `875` tiles | 4 banners in `BR1`, crest + 3 banners in `BR2` |
| 7 | Bracket Nameplates | `0x09AED0..0x09D3B0` | `16 x 4x7` raw map + `267` raw tiles | `267` tiles (`pal=1`, bg `0`, outline `8`, fill `9`) | 16 opponent plates on bracket tree |
| 8 | In-Game Nameplates | `0x04D956..0x04FB76` | `16` `u32` ptrs + `16 x 9x3` raw maps + `244` raw tiles | `244` tiles (`[0..3,11,19,29,40,66]` protected) | Horizontal nameplates (`pal=14`, ink `8`) |
| 9 | Jade Emperor Speeches | `0x0FC128..0x0FF0F6`, `0x00E884` | `71` sprites (`329` tiles) + `6` streams | `63` text sprites (`#6..#68`), `#69/#70` blank, `329` tiles | 6 streams rendered as `3x5` (`48x80`) `16x16` sprite pages; `0x00E8F8` converted to row-major, `0x00E8AC`/`0x00E8C2` hooks disabled |
| 10 | Set 1 Table Prompts & Taunts | `0x0379EE..0x03E80A` | `59` sprites (`#0..#58`), raw tiles | `787` tiles (`#21, #22, #45` protected) | Player/seat indicators, Chow/Pong/Kong/Win stamps, Cheat activation banners, waiting taunts |
| 11 | Set 2 Yaku, Rivals & HUD | `0x03E80A..0x043FA6` | `90` sprites (`#0..#89`), raw tiles | `598` tiles (`#84` protected) | 63 Yaku/Streak entries, 16 opponent names (`#63..#78`), HUD/status (`#79..#89`) |
| 12 | Set 3 Opponent Quips | `0x043FA6..0x04D956`, `0x04FB76..0x04FDF2` | `116` sprites (`#0..#115`) + `68` quip pointers | `995` tiles (`#114, #115` speech bubbles protected) | `0x00E3F8` displays 1-line inside `#114` and 2-line `[A, B]` inside `#115` |
| 13 | Cheat Skill Overlay | `0x07F4D0..0x0826D8` | `2x2` alt stat + `32x25` map + frame + `300` tiles | `300` tiles (`1..65` frame protected) | Stats (`VITAL`, `SPIRIT`, `GOLD`) + 10 cheat skills and costs (`pal=8`) |
| 14 | Leaderboard Screen (`LB2`) | `0x087C98..0x089C98` | Raw `64x32` map + `128` raw tiles | `128` tiles (`[0..17, 44, 103..127]` protected) | Column headers (`RANK, NAME, CASH, WINS, SELF, DEAL`) + ranks `1ST..4TH` (`pal=3`) |
| 15 | Mini-Game Backgrounds | `0x011B64..0x01B0C4` | 3 raw `64x32` maps (`232`, `300`, `279` tiles) | `232` / `300` / `279` tiles | Signboard (`TRIPLE HIT`, `TWIN CANNON`, `BLACKJACK`) + felt watermark removal/cleanup |
| 16 | Bank 3 Mini-Game Sprites | `0x01B0C4..0x01FCE8` | `28` sprites (`#0..#27`), raw `545` tiles | `545` tiles (`#4..6, #9..10, #13..17, #19..21, #26..27` protected) | Start prompt, table plaques, reward/Heal banners, Odds board header, HIT/STAY/PUSH |
| 17 | Ending Credits | `0x024CCC..0x025690` | `0xF3` `32x64` map + `0xF3` `240` tiles | `240` tiles (keep `<= 240` for VRAM safety) | Staff credits (`PLANNER`, `ART`, `PROGRAMMING`, `MUSIC`, `DUNHUANG TECHNOLOGY`) + preserved `FUNTECH ENTERTAINMENT CORP. 1995` |
