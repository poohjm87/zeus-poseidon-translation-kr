#!/usr/bin/env python3
"""Zeus + Poseidon Steam EXE Binary Patcher for Korean Text Rendering

All handler code is placed in the new .krfnt PE section (read+write+exec),
avoiding the code cave size limitation at 0x5D7360.
"""

import struct, sys, os, argparse

BASE_VA = 0x400000
PIXEL_BUF_PTR = 0xF9C100
PITCH_PTR = 0xF2A698

PP1_VA, PP1_FILE = 0x508955, 0x108955
PP1_ORIG = bytes.fromhex('3c2073ad33f6')
PP2_VA, PP2_FILE = 0x507F20, 0x107F20
PP3_VA, PP3_FILE = 0x5091CB, 0x1091CB
PP3_ORIG = bytes.fromhex('8a034384c0')
PP4_VA, PP4_FILE = 0x507DA0, 0x107DA0
PP4_ORIG = bytes.fromhex('83ec088b1520c82b01')  # 9 bytes
PP5_VA, PP5_FILE = 0x4F592B, 0x0F592B
PP5_ORIG = bytes.fromhex('80fb207264')            # 5 bytes: cmp bl,0x20; jb +0x64
PP6_VA, PP6_FILE = 0x4F57BA, 0x0F57BA
PP6_ORIG = bytes.fromhex('8a064684c0')            # 5 bytes: mov al,[esi]; inc esi; test al,al
PP7_VA, PP7_FILE = 0x4230C9, 0x0230C9
PP7_ORIG = bytes.fromhex('0FBEC86A0151')           # 6 bytes: movsx ecx,al; push 1; push ecx
PP7_RETURN = 0x4230DD                               # ret at end of original block
POST_DRAW_VA = 0x508A28
CTRL_CHAR_VA = 0x508A7B
PRINTABLE_VA = 0x508906
KFONT_GLYPH_COUNT = 2350
KFONT_TOTAL_SIZE = 2350 * 32
ASCII_GLYPH_COUNT = 96   # 0x20-0x7F
ASCII_TOTAL_SIZE = 96 * 32
TITLE_FONT_SIZE = 2350 * 32  # title-size Korean KFONT (18px in 16 rows)

# .krfnt section layout
GLOBALS_SIZE = 256       # [0x000] globals (skip_flag at +0x10)
HANDLER_OFF  = 0x100     # [0x100] Korean text handler (up to 560 bytes with title)
GCW_OFF      = 0x340     # [0x340] get_char_width handler (77 bytes)
WW_OFF       = 0x390     # [0x390] word_wrap handler
CSW_OFF      = 0x400     # [0x400] calc_string_width handler
TT_OFF       = 0x600     # [0x600] tooltip_draw handler
PW_OFF       = 0xA00     # [0xA00] popup word width DBCS handler
AB_OFF       = 0xA80     # [0xA80] (unused)
CODE_SIZE    = 0xC00     # total code+globals area before font data

def le32(v): return struct.pack('<I', v & 0xFFFFFFFF)
def rel32(frm, to): return struct.pack('<i', to - frm)
def jmp32(frm, to): return b'\xE9' + rel32(frm + 5, to)


def build_korean_handler(handler_va, font_large_va, font_small_va, globals_va,
                         ascii_large_va=0, ascii_small_va=0, title_font_va=0):
    """Korean handler with DBCS trail byte skip, defensive bounds checks,
    and 3-tier font size selection: title(>20), large(>13), small(<=13)."""
    c = bytearray()
    P = handler_va
    SKIP_FLAG = globals_va + 0x10
    ADV_WIDTH = globals_va + 0x14  # advance width storage
    SPRITE_RECORDS_PTR = 0x012AFBE8

    # ---- SKIP FLAG CHECK ----
    # If previous iteration was a Korean lead, skip this trail byte
    c += b'\x80\x3D' + le32(SKIP_FLAG) + b'\x00'  # cmp byte [SKIP_FLAG], 0
    skip_trail_off = len(c)
    c += b'\x74\x00'                          # jz .no_skip (placeholder)
    c += b'\xC6\x05' + le32(SKIP_FLAG) + b'\x00'  # mov byte [SKIP_FLAG], 0
    c += b'\x33\xF6'                          # xor esi, esi (advance=0)
    c += b'\xE9' + rel32(P + len(c) + 5, POST_DRAW_VA)
    no_skip_off = len(c)
    c[skip_trail_off + 1] = no_skip_off - (skip_trail_off + 2)

    # ---- HIGH BYTE GATE ----
    # Catch ALL bytes >= 0x80 to prevent original glyph table access
    c += b'\x3C\x80'                          # cmp al, 0x80
    not_high_off = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'            # jb .not_high (ASCII < 0x80)

    # ---- DBCS TRAIL CHECK ----
    # Peek at next byte to determine if this is a DBCS lead
    c += b'\x8B\x4C\x24\x18'                  # mov ecx,[esp+0x18] (string ptr)
    c += b'\x8A\x49\x01'                      # mov cl,[ecx+1] (peek next)
    c += b'\x80\xF9\xA1'                      # cmp cl,0xA1
    no_dbcs_off = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'            # jb .no_dbcs (near jump)
    # Valid DBCS pair: set skip flag for trail byte
    c += b'\xC6\x05' + le32(SKIP_FLAG) + b'\x01'  # mov byte [SKIP_FLAG], 1

    # ---- RENDERABLE KOREAN CHECK ----
    # Only render if lead=0xB0-0xC8 (KS X 1001 Hangul range)
    c += b'\x3C\xB0'                          # cmp al, 0xB0
    skip_render_off1 = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'            # jb .skip_render (near)
    c += b'\x3C\xC8'                          # cmp al, 0xC8
    skip_render_off2 = len(c)
    c += b'\x0F\x87' + b'\0\0\0\0'            # ja .skip_render (near)

    # ---- RENDER KOREAN GLYPH ----
    c += b'\x60'                               # pushad (+32 on stack)

    c += b'\x0F\xB6\x44\x24\x1C'             # movzx eax, byte[esp+0x1C] ; lead
    c += b'\x0F\xB6\x4C\x24\x18'             # movzx ecx, byte[esp+0x18] ; trail

    # glyph_idx = (lead-0xB0)*94 + (trail-0xA1)
    c += b'\x2D' + le32(0xB0)                 # sub eax,0xB0
    c += b'\x6B\xC0\x5E'                      # imul eax,94
    c += b'\x81\xE9' + le32(0xA1)             # sub ecx,0xA1
    c += b'\x01\xC8'                          # add eax,ecx

    c += b'\x3D' + le32(2350)                  # cmp eax,2350
    sk1 = len(c)
    c += b'\x0F\x83' + b'\0\0\0\0'            # jae .render_skip

    # Validate pixel buffer
    c += b'\x8B\x35' + le32(PIXEL_BUF_PTR)   # mov esi,[pixel_buf]
    c += b'\x81\xFE\x00\x00\x01\x00'          # cmp esi,0x10000
    sk2 = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'            # jb .render_skip

    # Validate surface dimensions and pitch (must be > 0)
    # IMPORTANT: Do NOT clobber EAX (holds glyph index)
    c += b'\x8B\x3D' + le32(0xF2A6A0)        # mov edi,[surf_width]
    c += b'\x85\xFF'                          # test edi,edi
    sk_w = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'            # jz .render_skip
    c += b'\x8B\x3D' + le32(0xF2A69C)        # mov edi,[surf_height]
    c += b'\x85\xFF'                          # test edi,edi
    sk_h = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'            # jz .render_skip
    c += b'\x8B\x3D' + le32(PITCH_PTR)       # mov edi,[pitch]
    c += b'\x85\xFF'                          # test edi,edi
    sk_p = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'            # jz .render_skip

    # Bounds check: x+16 <= width, y+16 <= height (16 = max glyph rows)
    c += b'\x8B\x3C\x24'                      # mov edi,[esp] ; saved edi=x
    c += b'\x83\xC7\x10'                      # add edi,16
    c += b'\x3B\x3D' + le32(0xF2A6A0)        # cmp edi,[surf_width]
    sk3 = len(c)
    c += b'\x0F\x8F' + b'\0\0\0\0'            # jg .render_skip
    c += b'\x8B\x7C\x24\x40'                  # mov edi,[esp+0x40] ; y
    c += b'\x83\xC7\x10'                      # add edi,16
    c += b'\x3B\x3D' + le32(0xF2A69C)        # cmp edi,[surf_height]
    sk4 = len(c)
    c += b'\x0F\x8F' + b'\0\0\0\0'            # jg .render_skip

    # ---- FONT SIZE SELECTION ----
    # Read sprite height from sprite records using font_base
    # font_base = [esp+0x44] after pushad
    Y_OFFSET = globals_va + 0x18  # y offset: 3 for large, 1 for small
    DIAG_FB = globals_va + 0x20   # diagnostic: last font_base
    DIAG_SH = globals_va + 0x24   # diagnostic: last sprite_height
    c += b'\x8B\x5C\x24\x44'                 # mov ebx,[esp+0x44] ; font_base
    c += b'\x89\x1D' + le32(DIAG_FB)         # mov [DIAG_FB],ebx (diagnostic)
    c += b'\x8B\x3D' + le32(SPRITE_RECORDS_PTR)  # mov edi,[records_base]
    c += b'\x85\xFF'                          # test edi,edi
    use_large_off = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'            # jz .use_large (near)
    c += b'\x85\xDB'                          # test ebx,ebx
    use_large_off2 = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'            # jz .use_large (near)
    c += b'\x6B\xDB\x48'                      # imul ebx,ebx,72
    c += b'\x0F\xBF\x5C\x1F\x16'             # movsx ebx,word[edi+ebx+0x16]
    c += b'\x89\x1D' + le32(DIAG_SH)         # mov [DIAG_SH],ebx (diagnostic)
    c += b'\x83\xFB\x0D'                      # cmp ebx,13
    use_large_off3 = len(c)
    c += b'\x0F\x8F' + b'\0\0\0\0'            # jg .use_large_or_title (sprite_h > 13)
    # Small font path (sprite_h <= 13)
    c += b'\x8B\x35' + le32(PIXEL_BUF_PTR)   # mov esi,[pixel_buf]
    c += b'\xC1\xE0\x05'                      # shl eax,5
    c += b'\xBA' + le32(font_small_va)         # mov edx,font_small
    c += b'\x01\xC2'                          # add edx,eax
    c += b'\xC7\x05' + le32(ADV_WIDTH) + le32(9)   # [ADV_WIDTH]=9
    c += b'\xC7\x05' + le32(Y_OFFSET) + le32(4)   # [Y_OFFSET]=4
    c += b'\xBB\x0B\x00\x00\x00'              # mov ebx,11 (rows)
    font_done_off = len(c)
    c += b'\xE9' + b'\0\0\0\0'                # jmp .font_done (near)
    # .use_large_or_title: (sprite_h > 13)
    use_large = len(c)
    struct.pack_into('<i', c, use_large_off+2, use_large-(use_large_off+6))
    struct.pack_into('<i', c, use_large_off2+2, use_large-(use_large_off2+6))
    struct.pack_into('<i', c, use_large_off3+2, use_large-(use_large_off3+6))
    # Check title font (sprite_h > 20) → use title KFONT
    c += b'\x83\xFB\x14'                      # cmp ebx,20
    use_normal_large = len(c)
    c += b'\x0F\x8E' + b'\0\0\0\0'            # jle .use_normal_large
    # Title font path (sprite_h > 20) — use 18px title KFONT
    c += b'\x8B\x35' + le32(PIXEL_BUF_PTR)
    c += b'\xC1\xE0\x05'                      # shl eax,5
    c += b'\xBA' + le32(title_font_va)         # mov edx,title_font (18px glyphs)
    c += b'\x01\xC2'
    c += b'\xC7\x05' + le32(ADV_WIDTH) + le32(18)  # [ADV_WIDTH]=18
    c += b'\xC7\x05' + le32(Y_OFFSET) + struct.pack('<i', -5)  # [Y_OFFSET]=-5 (move DOWN by 5px)
    c += b'\xBB\x10\x00\x00\x00'              # mov ebx,16 (rows)
    font_done_off2 = len(c)
    c += b'\xE9' + b'\0\0\0\0'                # jmp .font_done
    # .use_normal_large:
    use_normal_large_pos = len(c)
    struct.pack_into('<i', c, use_normal_large+2, use_normal_large_pos-(use_normal_large+6))
    c += b'\x8B\x35' + le32(PIXEL_BUF_PTR)   # mov esi,[pixel_buf]
    c += b'\xC1\xE0\x05'                      # shl eax,5
    c += b'\xBA' + le32(font_large_va)         # mov edx,font_large
    c += b'\x01\xC2'                          # add edx,eax
    c += b'\xC7\x05' + le32(ADV_WIDTH) + le32(14)  # [ADV_WIDTH]=14
    c += b'\xC7\x05' + le32(Y_OFFSET) + le32(3)   # [Y_OFFSET]=3 (large)
    c += b'\xBB\x10\x00\x00\x00'              # mov ebx,16 (rows)
    # .font_done:
    font_done = len(c)
    struct.pack_into('<i', c, font_done_off+1, font_done-(font_done_off+5))
    struct.pack_into('<i', c, font_done_off2+1, font_done-(font_done_off2+5))

    # dest = pixel_buf + (y-offset)*pitch + x*2
    # Y_OFFSET: 3 for large font, 5 for small font (moves small text UP)
    c += b'\x8B\x44\x24\x40'                  # mov eax,[esp+0x40] ; y
    c += b'\x2B\x05' + le32(Y_OFFSET)        # sub eax,[Y_OFFSET]
    c += b'\x78\x02'                          # js +2
    c += b'\xEB\x02'                          # jmp +2
    c += b'\x33\xC0'                          # xor eax,eax
    c += b'\x0F\xAF\x05' + le32(PITCH_PTR)   # imul eax,[pitch]
    c += b'\x01\xC6'                          # add esi,eax
    c += b'\x8B\x3C\x24'                      # mov edi,[esp] ; saved edi=x
    c += b'\x8D\x34\x7E'                      # lea esi,[esi+edi*2]

    # Render rows (ebx=row count: 11 or 16)
    c += b'\x89\xD9'                          # mov ecx,ebx
    rr = len(c)
    c += b'\x0F\xB6\x02'                      # movzx eax,[edx]
    c += b'\xC1\xE0\x08'                      # shl eax,8
    c += b'\x0F\xB6\x5A\x01'                  # movzx ebx,[edx+1]
    c += b'\x09\xD8'                          # or eax,ebx
    c += b'\x8B\xFE'                          # mov edi,esi
    c += b'\xBB\x10\x00\x00\x00'              # mov ebx,16
    il = len(c)
    c += b'\xA9\x00\x80\x00\x00'              # test eax,0x8000
    c += b'\x74\x05'                          # jz +5 (skip 5-byte mov)
    c += b'\x66\xC7\x07\xFF\xFF'              # mov word[edi],0xFFFF (white pixel)
    c += b'\xD1\xE0'                          # shl eax,1
    c += b'\x83\xC7\x02'                      # add edi,2
    c += b'\x4B'                              # dec ebx
    c += b'\x75' + struct.pack('b', il - (len(c) + 2))
    c += b'\x83\xC2\x02'                      # add edx,2
    c += b'\x03\x35' + le32(PITCH_PTR)        # add esi,[pitch]
    c += b'\x49'                              # dec ecx
    c += b'\x75' + struct.pack('b', rr - (len(c) + 2))

    # .render_skip (after pushad: popad + advance)
    sk = len(c)
    struct.pack_into('<i', c, sk1+2, sk-(sk1+6))
    struct.pack_into('<i', c, sk2+2, sk-(sk2+6))
    struct.pack_into('<i', c, sk_w+2, sk-(sk_w+6))
    struct.pack_into('<i', c, sk_h+2, sk-(sk_h+6))
    struct.pack_into('<i', c, sk_p+2, sk-(sk_p+6))
    struct.pack_into('<i', c, sk3+2, sk-(sk3+6))
    struct.pack_into('<i', c, sk4+2, sk-(sk4+6))

    c += b'\x61'                              # popad
    c += b'\x8B\x35' + le32(ADV_WIDTH)        # mov esi,[ADV_WIDTH] (10 or 14)
    c += b'\xE9' + rel32(P + len(c) + 5, POST_DRAW_VA)

    # .skip_render (DBCS non-renderable: advance=14, no render)
    skip_render = len(c)
    struct.pack_into('<i', c, skip_render_off1+2, skip_render-(skip_render_off1+6))
    struct.pack_into('<i', c, skip_render_off2+2, skip_render-(skip_render_off2+6))

    c += b'\xBE\x0E\x00\x00\x00'              # mov esi,14 (advance width)
    c += b'\xE9' + rel32(P + len(c) + 5, POST_DRAW_VA)

    # .no_dbcs: single high byte (not DBCS pair), skip with advance=0
    no_dbcs = len(c)
    struct.pack_into('<i', c, no_dbcs_off+2, no_dbcs-(no_dbcs_off+6))
    c += b'\x33\xF6'                          # xor esi,esi (advance=0)
    c += b'\xE9' + rel32(P + len(c) + 5, POST_DRAW_VA)

    # .not_high: ASCII < 0x80
    not_high = len(c)
    struct.pack_into('<i', c, not_high_off+2, not_high-(not_high_off+6))
    c += b'\x3C\x20'                          # cmp al,0x20
    ctrl_off = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'           # jb .ctrl_char (near)

    # Normal ASCII path (game sprite font)
    c += b'\x0F\x83' + rel32(P + len(c) + 6, PRINTABLE_VA)
    c += b'\x33\xF6'                          # xor esi,esi
    c += b'\xE9' + rel32(P + len(c) + 5, CTRL_CHAR_VA)

    # .ctrl_char
    ctrl_char = len(c)
    struct.pack_into('<i', c, ctrl_off+2, ctrl_char-(ctrl_off+6))
    c += b'\x33\xF6'
    c += b'\xE9' + rel32(P + len(c) + 5, CTRL_CHAR_VA)
    return bytes(c)


def build_gcw_handler(handler_va, globals_va):
    """get_char_width handler - uses font_base (2nd param) to determine width.
    Signature: int get_char_width(int char_byte, int font_base)"""
    SPRITE_RECORDS_PTR = 0x012AFBE8
    c = bytearray()
    P = handler_va
    c += b'\x8B\x44\x24\x04'                  # mov eax,[esp+4] ; char_byte
    c += b'\x3C\x80'                          # cmp al,0x80
    not_high = len(c)
    c += b'\x72\x00'                          # jb .normal (placeholder)
    # High byte: determine width from font_base sprite height
    c += b'\x53'                              # push ebx
    c += b'\x57'                              # push edi
    c += b'\x8B\x5C\x24\x10'                  # mov ebx,[esp+0x10] ; font_base (+8 for pushes)
    c += b'\x8B\x3D' + le32(SPRITE_RECORDS_PTR)  # mov edi,[records_base]
    c += b'\x85\xFF'                          # test edi,edi
    large_w1 = len(c)
    c += b'\x74\x00'                          # jz .large_w
    c += b'\x85\xDB'                          # test ebx,ebx
    large_w2 = len(c)
    c += b'\x74\x00'                          # jz .large_w
    c += b'\x6B\xDB\x48'                      # imul ebx,ebx,72
    c += b'\x0F\xBF\x5C\x1F\x16'             # movsx ebx,word[edi+ebx+0x16]
    c += b'\x83\xFB\x0D'                      # cmp ebx,13
    large_w3 = len(c)
    c += b'\x7F\x00'                          # jg .large_or_title_w
    # Small font: return 10
    c += b'\x5F'                              # pop edi
    c += b'\x5B'                              # pop ebx
    c += b'\xB8\x0A\x00\x00\x00'              # mov eax,10
    c += b'\xC3'                              # ret
    # .large_or_title_w:
    large_w = len(c)
    c[large_w1 + 1] = large_w - (large_w1 + 2)
    c[large_w2 + 1] = large_w - (large_w2 + 2)
    c[large_w3 + 1] = large_w - (large_w3 + 2)
    # Check title (sprite_h > 20)
    c += b'\x83\xFB\x14'                      # cmp ebx,20
    normal_large = len(c)
    c += b'\x7E\x00'                          # jle .normal_large_w
    # Title: return 18
    c += b'\x5F'                              # pop edi
    c += b'\x5B'                              # pop ebx
    c += b'\xB8\x12\x00\x00\x00'              # mov eax,18
    c += b'\xC3'                              # ret
    # .normal_large_w: return 15
    normal_large_pos = len(c)
    c[normal_large + 1] = normal_large_pos - (normal_large + 2)
    c += b'\x5F'                              # pop edi
    c += b'\x5B'                              # pop ebx
    c += b'\xB8\x0F\x00\x00\x00'              # mov eax,15
    c += b'\xC3'                              # ret
    # .normal: ASCII, use original function
    normal = len(c)
    c[not_high + 1] = normal - (not_high + 2)
    c += b'\x84\xC0'                          # test al,al
    c += b'\xE9' + rel32(P + len(c) + 5, 0x507F26)
    return bytes(c)


def build_ww_handler(handler_va):
    """word_wrap DBCS skip handler - handles ALL high byte leads (>=0x80).
    CRITICAL: Also increments char_count [0xF13A58] for trail byte so that
    word_wrap_draw's byte copy loop copies the correct number of bytes.
    Without this, trail bytes are skipped in the copy → DBCS pairs break."""
    CHAR_COUNT = 0xF13A58
    c = bytearray()
    c += b'\x8A\x03'                          # mov al,[ebx]
    c += b'\x43'                              # inc ebx
    c += b'\x3C\x80'                          # cmp al,0x80
    jb1 = len(c)
    c += b'\x72\x00'                          # jb .no (placeholder)
    c += b'\x80\x3B\xA1'                      # cmp byte[ebx],0xA1
    jb2 = len(c)
    c += b'\x72\x00'                          # jb .no (placeholder)
    c += b'\x43'                              # inc ebx (skip trail byte)
    c += b'\xFF\x05' + le32(CHAR_COUNT)       # inc dword [char_count] (+1 for trail byte)
    # .no:
    no = len(c)
    c[jb1 + 1] = no - (jb1 + 2)
    c[jb2 + 1] = no - (jb2 + 2)
    c += b'\x84\xC0'                          # test al,al
    c += b'\xE9' + rel32(handler_va + len(c) + 5, PP3_VA + 5)
    return bytes(c)


def build_pw_handler(handler_va):
    """Popup word width DBCS handler — hooks at 0x4F57BA inside 0x4F5799.
    For Korean DBCS pairs: skips trail byte AND adds correct Korean pixel
    width to edi (the width accumulator), bypassing the original Latin-1
    char width lookup (0x507F20) which returns wrong widths for lead bytes.
    Width is determined from sprite height via font_base at [0xEF8C9C]."""
    CHAR_COUNT = 0xF13A58
    FONT_BASE_GLOBAL = 0xEF8C9C
    SPRITE_RECORDS_PTR = 0x012AFBE8
    # After DBCS handling, jump to char_count increment + loop at 0x4F584C
    CHARCOUNT_INC = 0x4F584C
    c = bytearray()
    P = handler_va

    c += b'\x8A\x06'                          # mov al,[esi]
    c += b'\x46'                              # inc esi
    c += b'\x3C\x80'                          # cmp al,0x80
    jb1 = len(c)
    c += b'\x72\x00'                          # jb .not_korean (placeholder)
    c += b'\x80\x3E\xA1'                      # cmp byte[esi],0xA1
    jb2 = len(c)
    c += b'\x72\x00'                          # jb .not_korean (placeholder)

    # --- DBCS pair detected ---
    c += b'\x46'                              # inc esi (skip trail byte)

    # Determine Korean width from sprite height
    c += b'\x52'                              # push edx (save)
    c += b'\x50'                              # push eax (save lead byte)
    c += b'\x8B\x15' + le32(FONT_BASE_GLOBAL) # mov edx,[font_base_global]
    c += b'\xA1' + le32(SPRITE_RECORDS_PTR)   # mov eax,[records_base]
    c += b'\x85\xC0'                          # test eax,eax
    jz1 = len(c)
    c += b'\x74\x00'                          # jz .width_large (placeholder)
    c += b'\x85\xD2'                          # test edx,edx
    jz2 = len(c)
    c += b'\x74\x00'                          # jz .width_large (placeholder)
    c += b'\x6B\xD2\x48'                      # imul edx,edx,72
    c += b'\x0F\xBF\x54\x10\x16'             # movsx edx,word[eax+edx+0x16] (sprite_h)
    c += b'\x83\xFA\x0D'                      # cmp edx,13
    jg1 = len(c)
    c += b'\x7F\x00'                          # jg .check_title (placeholder)
    # Small font: width=10
    c += b'\x58'                              # pop eax
    c += b'\x5A'                              # pop edx
    c += b'\x83\xC7\x0A'                      # add edi,10
    jmp_done1 = len(c)
    c += b'\xEB\x00'                          # jmp .done (placeholder)

    # .check_title:
    check_title = len(c)
    c[jg1 + 1] = check_title - (jg1 + 2)
    c += b'\x83\xFA\x14'                      # cmp edx,20
    jle1 = len(c)
    c += b'\x7E\x00'                          # jle .width_large (placeholder)
    # Title font: width=18
    c += b'\x58'                              # pop eax
    c += b'\x5A'                              # pop edx
    c += b'\x83\xC7\x12'                      # add edi,18
    jmp_done2 = len(c)
    c += b'\xEB\x00'                          # jmp .done (placeholder)

    # .width_large: (default, also for records_base=0 or font_base=0)
    width_large = len(c)
    c[jz1 + 1] = width_large - (jz1 + 2)
    c[jz2 + 1] = width_large - (jz2 + 2)
    c[jle1 + 1] = width_large - (jle1 + 2)
    c += b'\x58'                              # pop eax
    c += b'\x5A'                              # pop edx
    c += b'\x83\xC7\x0F'                      # add edi,15

    # .done:
    done = len(c)
    c[jmp_done1 + 1] = done - (jmp_done1 + 2)
    c[jmp_done2 + 1] = done - (jmp_done2 + 2)
    c += b'\xB9\x01\x00\x00\x00'             # mov ecx,1 (seen-char flag)
    c += b'\x88\x44\x24\x10'                  # mov [esp+0x10],al (store char)
    c += b'\xFF\x05' + le32(CHAR_COUNT)       # inc dword [char_count] (+1 for trail byte)
    c += b'\xE9' + rel32(P + len(c) + 5, CHARCOUNT_INC)  # jmp to main loop inc

    # .not_korean:
    not_korean = len(c)
    c[jb1 + 1] = not_korean - (jb1 + 2)
    c[jb2 + 1] = not_korean - (jb2 + 2)
    c += b'\x84\xC0'                          # test al,al
    c += b'\xE9' + rel32(P + len(c) + 5, PP6_VA + 5)
    return bytes(c)


def build_ab_handler(handler_va, font_large_va, font_small_va, globals_va):
    """Adventure bitmap font Korean handler — hooks at 0x4230C9.
    When AL >= 0x80 (Korean lead byte), renders KFONT glyph to pixel buffer
    instead of calling bitmap font renderer. For ASCII, executes original code.
    Original 21 bytes at 0x4230C9-0x4230DD replaced with JMP + NOPs."""
    c = bytearray()
    P = handler_va
    PIXEL_BUF_PTR = 0xF9C100
    PITCH_PTR = 0xF2A698
    AB_SKIP = globals_va + 0x40     # skip flag for trail byte
    CHAR_BUF = 0xF2A7B0             # current char buffer (game global)
    SPRITE_RECORDS_PTR = 0x012AFBE8

    # ---- CHECK: Korean or ASCII? ----
    c += b'\x3C\x80'                                # cmp al, 0x80
    ascii_off = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'                  # jb .ascii_path (near)

    # ---- KOREAN PATH ----
    # Check skip flag (trail byte from previous call)
    c += b'\x80\x3D' + le32(AB_SKIP) + b'\x00'      # cmp byte [AB_SKIP], 0
    no_skip_off = len(c)
    c += b'\x74\x00'                                 # jz .no_skip
    # Trail byte: clear flag and return
    c += b'\xC6\x05' + le32(AB_SKIP) + b'\x00'      # mov byte [AB_SKIP], 0
    c += b'\xC3'                                     # ret (skip this char)
    # .no_skip:
    no_skip = len(c)
    c[no_skip_off + 1] = no_skip - (no_skip_off + 2)

    # Read next byte from char buffer to check DBCS trail
    # The game processes chars one at a time; next char is in the text stream
    # We need to peek ahead. The text buffer pointer is somewhere in the caller.
    # Simpler approach: check if AL is in Hangul lead range (0xB0-0xC8)
    c += b'\x3C\xB0'                                # cmp al, 0xB0
    skip_kr_off1 = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'                  # jb .skip_korean
    c += b'\x3C\xC8'                                # cmp al, 0xC8
    skip_kr_off2 = len(c)
    c += b'\x0F\x87' + b'\0\0\0\0'                  # ja .skip_korean

    # Set skip flag for next call (trail byte)
    c += b'\xC6\x05' + le32(AB_SKIP) + b'\x01'      # mov byte [AB_SKIP], 1

    # ---- RENDER KFONT ----
    c += b'\x60'                                     # pushad

    # Validate pixel buffer
    c += b'\x8B\x35' + le32(PIXEL_BUF_PTR)          # mov esi, [pixel_buf]
    c += b'\x81\xFE\x00\x00\x01\x00'                # cmp esi, 0x10000
    sk1 = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'                  # jb .render_skip

    c += b'\x8B\x3D' + le32(PITCH_PTR)              # mov edi, [pitch]
    c += b'\x85\xFF'                                 # test edi, edi
    sk2 = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'                  # jz .render_skip

    # We need the lead byte (in AL before pushad → now [esp+0x1C] after pushad)
    # Actually AL was already pushed as part of EAX in pushad
    # Get it from saved EAX on stack
    c += b'\x0F\xB6\x44\x24\x1C'                    # movzx eax, byte [esp+0x1C] (saved AL)

    # We need trail byte. Since we process one char at a time,
    # the trail byte will come in the NEXT call. We stored the lead byte;
    # we need to get the trail byte NOW.
    # The text is being fed from the game's text stream.
    # Let's try reading from the text source pointer.
    # The game's adventure text is at a buffer; we can read the NEXT byte
    # from the char buffer area.
    # Actually, the char comes from [0xF2A7B0]. The game reads chars sequentially.
    # We can't peek the next char here. Instead, store the lead byte
    # and render when the trail byte arrives.

    # ALTERNATIVE: Store lead byte, skip render. On next call (trail byte),
    # combine lead+trail and render.

    c += b'\x61'                                     # popad (abort render for now)

    # Store lead byte in globals for next call
    c += b'\xA2' + le32(globals_va + 0x44)           # mov [lead_store], al

    c += b'\xC3'                                     # ret (skip bitmap render)

    # .skip_korean: high byte but not Hangul lead → check if it's trail byte
    skip_kr = len(c)
    struct.pack_into('<i', c, skip_kr_off1+2, skip_kr-(skip_kr_off1+6))
    struct.pack_into('<i', c, skip_kr_off2+2, skip_kr-(skip_kr_off2+6))

    # Check if skip flag is set (this might be a trail byte)
    c += b'\x80\x3D' + le32(AB_SKIP) + b'\x00'      # cmp byte [AB_SKIP], 0
    not_trail_off = len(c)
    c += b'\x74\x00'                                 # jz .not_trail
    # This is a trail byte! Clear flag, combine with stored lead, render
    c += b'\xC6\x05' + le32(AB_SKIP) + b'\x00'      # clear skip flag

    c += b'\x60'                                     # pushad

    # Validate pixel buffer
    c += b'\x8B\x35' + le32(PIXEL_BUF_PTR)
    c += b'\x81\xFE\x00\x00\x01\x00'
    sk3 = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'                  # jb .render_skip

    c += b'\x8B\x3D' + le32(PITCH_PTR)
    c += b'\x85\xFF'
    sk4 = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'                  # jz .render_skip

    # Get lead byte from stored value, trail from AL (current)
    c += b'\x0F\xB6\x05' + le32(globals_va + 0x44)  # movzx eax, [lead_store]
    c += b'\x0F\xB6\x4C\x24\x1C'                    # movzx ecx, [esp+0x1C] (saved AL=trail)

    # glyph_idx = (lead-0xB0)*94 + (trail-0xA1)
    c += b'\x2D' + le32(0xB0)                        # sub eax, 0xB0
    c += b'\x6B\xC0\x5E'                             # imul eax, 94
    c += b'\x81\xE9' + le32(0xA1)                    # sub ecx, 0xA1
    c += b'\x01\xC8'                                 # add eax, ecx

    c += b'\x3D' + le32(2350)                        # cmp eax, 2350
    sk5 = len(c)
    c += b'\x0F\x83' + b'\0\0\0\0'                  # jae .render_skip

    # Select font (always use large for adventure text)
    c += b'\xC1\xE0\x05'                             # shl eax, 5 (glyph_idx * 32)
    c += b'\xBA' + le32(font_large_va)               # mov edx, font_large
    c += b'\x01\xC2'                                 # add edx, eax
    c += b'\xBB\x10\x00\x00\x00'                    # mov ebx, 16 (rows)

    # Dest = pixel_buf + y*pitch + x*2
    # x = [0xF2A6AC], y = [0xF2A6A8] (set before char processing)
    c += b'\x8B\x05' + le32(0xF2A6A8)               # mov eax, [y_pos]
    c += b'\x0F\xAF\x05' + le32(PITCH_PTR)          # imul eax, [pitch]
    c += b'\x01\xC6'                                 # add esi, eax
    c += b'\x8B\x3D' + le32(0xF2A6AC)               # mov edi, [x_pos]
    c += b'\x8D\x34\x7E'                             # lea esi, [esi+edi*2]

    # Render 1bpp glyph (16 rows, 16 cols)
    c += b'\x89\xD9'                                 # mov ecx, ebx
    rr = len(c)
    c += b'\x0F\xB6\x02'                            # movzx eax, [edx]
    c += b'\xC1\xE0\x08'                            # shl eax, 8
    c += b'\x0F\xB6\x5A\x01'                        # movzx ebx, [edx+1]
    c += b'\x09\xD8'                                # or eax, ebx
    c += b'\x8B\xFE'                                # mov edi, esi
    c += b'\xBB\x10\x00\x00\x00'                    # mov ebx, 16
    il = len(c)
    c += b'\xA9\x00\x80\x00\x00'                    # test eax, 0x8000
    c += b'\x74\x05'                                # jz +5
    c += b'\x66\xC7\x07\xFF\xFF'                    # mov word [edi], 0xFFFF
    c += b'\xD1\xE0'                                # shl eax, 1
    c += b'\x83\xC7\x02'                            # add edi, 2
    c += b'\x4B'                                    # dec ebx
    c += b'\x75' + struct.pack('b', il - (len(c) + 2))
    c += b'\x83\xC2\x02'                            # add edx, 2
    c += b'\x03\x35' + le32(PITCH_PTR)              # add esi, [pitch]
    c += b'\x49'                                    # dec ecx
    c += b'\x75' + struct.pack('b', rr - (len(c) + 2))

    # .render_skip
    sk = len(c)
    for s in [sk1, sk2, sk3, sk4, sk5]:
        struct.pack_into('<i', c, s+2, sk-(s+6))

    c += b'\x61'                                     # popad
    c += b'\xC3'                                     # ret

    # .not_trail: high byte, not Hangul lead, not trail → just skip
    not_trail = len(c)
    c[not_trail_off + 1] = not_trail - (not_trail_off + 2)
    c += b'\xC3'                                     # ret (skip this char)

    # ---- ASCII PATH: execute original code ----
    ascii_path = len(c)
    struct.pack_into('<i', c, ascii_off+2, ascii_path-(ascii_off+6))
    # Original code: movsx ecx,al; push 1; push ecx; call 42B480; push eax; call 420370; add esp,0C; ret
    c += b'\x0F\xBE\xC8'                            # movsx ecx, al
    c += b'\x6A\x01'                                # push 1
    c += b'\x51'                                    # push ecx
    c += b'\xE8' + rel32(P + len(c) + 5, 0x42B480) # call 0x42B480
    c += b'\x50'                                    # push eax
    c += b'\xE8' + rel32(P + len(c) + 5, 0x420370) # call 0x420370
    c += b'\x83\xC4\x0C'                            # add esp, 0x0C
    c += b'\xC3'                                    # ret

    return bytes(c)


def build_csw_handler(handler_va, globals_va):
    """calc_string_width hook - handles Korean DBCS width calculation.
    Original: int calc_string_width(const char *string, int font_id)
    First 9 bytes replaced: sub esp,8; mov edx,[0x12BC820]
    Strategy: scan string for high bytes. If none, use original function.
    If has Korean, iterate and sum widths ourselves."""
    c = bytearray()
    P = handler_va
    ADV_WIDTH = globals_va + 0x14
    SPRITE_RECORDS_PTR = 0x012AFBE8
    CONTINUE_ORIG = PP4_VA + 9  # after replaced 9 bytes

    # Execute replaced instructions
    c += b'\x83\xEC\x08'                      # sub esp,8
    c += b'\x8B\x15\x20\xC8\x2B\x01'        # mov edx,[0x12BC820]

    # Scan string for high bytes
    # string = [esp+0x0C] (original esp+4, +8 for sub esp)
    c += b'\x50'                              # push eax (save)
    c += b'\x56'                              # push esi
    c += b'\x8B\x74\x24\x14'                  # mov esi,[esp+0x14] ; string (+8 for pushes)
    # .scan_loop:
    scan_loop = len(c)
    c += b'\x8A\x06'                          # mov al,[esi]
    c += b'\x84\xC0'                          # test al,al
    no_kr = len(c)
    c += b'\x74\x00'                          # jz .no_korean
    c += b'\x3C\x80'                          # cmp al,0x80
    has_kr = len(c)
    c += b'\x73\x00'                          # jae .has_korean
    c += b'\x46'                              # inc esi
    c += b'\xEB' + struct.pack('b', scan_loop - (len(c) + 2))  # jmp .scan_loop

    # .no_korean: no high bytes found, use original function
    no_korean = len(c)
    c[no_kr + 1] = no_korean - (no_kr + 2)
    c += b'\x5E'                              # pop esi
    c += b'\x58'                              # pop eax
    c += b'\xE9' + rel32(P + len(c) + 5, CONTINUE_ORIG)

    # .has_korean: calculate width ourselves
    has_korean = len(c)
    c[has_kr + 1] = has_korean - (has_kr + 2)
    c += b'\x5E'                              # pop esi
    c += b'\x58'                              # pop eax

    # Determine Korean char width from sprite records
    # Use font_group (edx = [0x12BC820] already loaded) to pick font_base
    # Then read sprite height. But we don't have font_base here easily.
    # Alternative: use edx (font_group) directly: group >= 15 → large, else small
    c += b'\x53'                              # push ebx
    c += b'\x55'                              # push ebp
    c += b'\x56'                              # push esi
    c += b'\x57'                              # push edi

    # Determine Korean advance width using font_id (2nd param) as font_base
    # font_id = [esp+0x20] (original esp+0x10, +8 sub esp, +16 pushes)
    c += b'\x8B\x6C\x24\x20'                  # mov ebp,[esp+0x20] ; font_id/font_base
    c += b'\xBB\x0E\x00\x00\x00'              # mov ebx,14 (default large)
    c += b'\x8B\x3D' + le32(0x012AFBE8)      # mov edi,[records_base]
    c += b'\x85\xFF'                          # test edi,edi
    csw_no_rec = len(c)
    c += b'\x74\x00'                          # jz .no_records (short)
    c += b'\x85\xED'                          # test ebp,ebp
    csw_no_rec2 = len(c)
    c += b'\x74\x00'                          # jz .no_records
    c += b'\x6B\xED\x48'                      # imul ebp,ebp,72
    c += b'\x0F\xBF\x6C\x2F\x16'             # movsx ebp,word[edi+ebp+0x16] ; sprite_h
    c += b'\x83\xFD\x0D'                      # cmp ebp,13
    csw_ws3 = len(c)
    c += b'\x7F\x05'                          # jg .check_title (sprite_h > 13)
    c += b'\xBB\x09\x00\x00\x00'              # mov ebx,9 (small)
    csw_ws_skip = len(c)
    c += b'\xEB\x00'                          # jmp .width_set (placeholder)
    # .check_title:
    c += b'\x83\xFD\x14'                      # cmp ebp,20
    csw_ws4 = len(c)
    c += b'\x7E\x05'                          # jle .width_set (keep large=14)
    c += b'\xBB\x12\x00\x00\x00'              # mov ebx,18 (title)
    csw_ws_skip2 = len(c)
    c += b'\xEB\x00'                          # jmp .width_set
    # .no_records: records_base=0 or font_base=0 → use defaults, ebp=0
    no_records = len(c)
    c[csw_no_rec + 1] = no_records - (csw_no_rec + 2)
    c[csw_no_rec2 + 1] = no_records - (csw_no_rec2 + 2)
    c += b'\x33\xED'                          # xor ebp,ebp (ebp=0 → ASCII stays 7px)
    # ebx stays 14 (default large Korean)
    # .width_set:
    width_set = len(c)
    c[csw_ws_skip + 1] = width_set - (csw_ws_skip + 2)
    c[csw_ws_skip2 + 1] = width_set - (csw_ws_skip2 + 2)

    c += b'\x8B\x74\x24\x1C'                  # mov esi,[esp+0x1C] ; string
    c += b'\x33\xFF'                          # xor edi,edi ; total = 0

    # .calc_loop:
    calc_loop = len(c)
    c += b'\x0F\xB6\x06'                      # movzx eax,byte[esi]
    c += b'\x85\xC0'                          # test eax,eax
    calc_done = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'            # jz .calc_done

    c += b'\x3C\x80'                          # cmp al,0x80
    calc_ascii = len(c)
    c += b'\x72\x00'                          # jb .calc_ascii

    # High byte: check DBCS trail
    c += b'\x80\x7E\x01\xA1'                  # cmp byte[esi+1],0xA1
    calc_single = len(c)
    c += b'\x72\x00'                          # jb .calc_single
    # DBCS pair: add Korean width
    c += b'\x01\xDF'                          # add edi,ebx
    c += b'\x83\xC6\x02'                      # add esi,2
    c += b'\xEB' + struct.pack('b', calc_loop - (len(c) + 2))

    # .calc_single: single high byte, skip
    calc_single_pos = len(c)
    c[calc_single + 1] = calc_single_pos - (calc_single + 2)
    c += b'\x46'                              # inc esi
    c += b'\xEB' + struct.pack('b', calc_loop - (len(c) + 2))

    # .calc_ascii: ASCII width (title-aware via ebp)
    calc_ascii_pos = len(c)
    c[calc_ascii + 1] = calc_ascii_pos - (calc_ascii + 2)
    # ebp = sprite_height (valid) or 0 (no records → default)
    c += b'\x83\xFD\x14'                      # cmp ebp,20
    csw_normal_ascii = len(c)
    c += b'\x7E\x00'                          # jle .normal_ascii
    # Title ASCII: 15px for chars, 10px for space
    c += b'\x3C\x20'                          # cmp al,0x20
    c += b'\x75\x03'                          # jnz .title_char
    c += b'\x83\xC7\x0A'                      # add edi,10 (title space)
    csw_next_a1 = len(c)
    c += b'\xEB\x00'                          # jmp .next_ascii
    # .title_char:
    c += b'\x83\xC7\x0F'                      # add edi,15 (title char)
    csw_next_a2 = len(c)
    c += b'\xEB\x00'                          # jmp .next_ascii
    # .normal_ascii:
    normal_ascii = len(c)
    c[csw_normal_ascii + 1] = normal_ascii - (csw_normal_ascii + 2)
    c += b'\x3C\x20'                          # cmp al,0x20
    c += b'\x75\x05'                          # jnz .not_space_csw
    c += b'\x83\xC7\x06'                      # add edi,6 (space width)
    c += b'\xEB\x03'                          # jmp .next_ascii
    # .not_space_csw:
    c += b'\x83\xC7\x07'                      # add edi,7 (avg ASCII width)
    # .next_ascii:
    next_ascii = len(c)
    c[csw_next_a1 + 1] = next_ascii - (csw_next_a1 + 2)
    c[csw_next_a2 + 1] = next_ascii - (csw_next_a2 + 2)
    c += b'\x46'                              # inc esi
    c += b'\xEB' + struct.pack('b', calc_loop - (len(c) + 2))

    # .calc_done: return total + left-shift correction
    calc_done_pos = len(c)
    struct.pack_into('<i', c, calc_done+2, calc_done_pos-(calc_done+6))
    c += b'\x89\xF8'                          # mov eax,edi (total width)
    # Left-shift correction based on font size
    c += b'\x83\xFD\x0D'                      # cmp ebp,13
    c += b'\x7E\x05'                          # jle .small_shift (+5)
    c += b'\x83\xC0\x0A'                      # add eax,10 (large: +10px left)
    c += b'\xEB\x03'                          # jmp .shift_done (+3)
    # .small_shift:
    c += b'\x83\xC0\x05'                      # add eax,5 (small: +5px left)
    # .shift_done:
    c += b'\x5F'                              # pop edi
    c += b'\x5E'                              # pop esi
    c += b'\x5D'                              # pop ebp
    c += b'\x5B'                              # pop ebx
    c += b'\x83\xC4\x08'                      # add esp,8 (undo sub esp,8)
    c += b'\xC3'                              # ret
    return bytes(c)


def build_tt_handler(handler_va, font_large_va, font_small_va, globals_va):
    """Tooltip draw Korean handler — hooks at 0x4F592B inside tooltip_draw loop.
    At hook point: BL=char byte, ESI=next char ptr, EBP=current x position.
    Stack (5 pushes): [esp+0x20]=y param.
    Renders Korean glyphs to the same pixel buffer as PP1 handler."""
    c = bytearray()
    P = handler_va
    TT_SKIP = globals_va + 0x30     # trail byte skip flag
    TT_ADV  = globals_va + 0x34     # advance width storage
    TT_YOFF = globals_va + 0x38     # y offset storage
    SPRITE_RECORDS_PTR = 0x012AFBE8

    # Jump targets within tooltip_draw
    TT_SKIP_CHAR = 0x4F5994    # load next char without advance (control chars)
    TT_ASCII_CONT = 0x4F5930   # continue original ASCII char processing
    TT_ADVANCE = 0x4F5992      # add ebp,eax; load next char; loop

    # ---- 1. SKIP FLAG CHECK (trail byte from previous Korean lead) ----
    c += b'\x80\x3D' + le32(TT_SKIP) + b'\x00'    # cmp byte [TT_SKIP], 0
    skip_off = len(c)
    c += b'\x74\x00'                                # jz .no_skip (short)
    # Skip flag was set — clear it
    c += b'\xC6\x05' + le32(TT_SKIP) + b'\x00'    # mov byte [TT_SKIP], 0
    # Verify this is actually a valid trail byte (not stale flag)
    c += b'\x80\xFB\xA1'                            # cmp bl, 0xA1
    process_normal_off = len(c)
    c += b'\x72\x00'                                # jb .process_normal (stale flag)
    # Valid trail byte: skip with advance=0
    c += b'\x33\xC0'                                # xor eax, eax
    c += b'\xE9' + rel32(P + len(c) + 5, TT_ADVANCE)

    # ---- 2. .no_skip ----
    no_skip = len(c)
    c[skip_off + 1] = no_skip - (skip_off + 2)
    # High byte check
    c += b'\x80\xFB\x80'                            # cmp bl, 0x80
    high_off = len(c)
    c += b'\x73\x00'                                # jae .high_byte (short)

    # ---- 3. .process_normal (ASCII — replaced instructions) ----
    process_normal = len(c)
    c[process_normal_off + 1] = process_normal - (process_normal_off + 2)
    c += b'\x80\xFB\x20'                            # cmp bl, 0x20
    c += b'\x0F\x82' + rel32(P + len(c) + 6, TT_SKIP_CHAR)  # jb → skip char
    c += b'\xE9' + rel32(P + len(c) + 5, TT_ASCII_CONT)      # jmp → ASCII path

    # ---- 4. .high_byte ----
    high_byte = len(c)
    c[high_off + 1] = high_byte - (high_off + 2)
    # Check if valid DBCS pair (trail byte >= 0xA1)
    c += b'\x80\x3E\xA1'                            # cmp byte [esi], 0xA1
    skip_single_off = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'                  # jb .skip_single (near)
    # Valid DBCS pair — set skip flag for trail byte next iteration
    c += b'\xC6\x05' + le32(TT_SKIP) + b'\x01'     # mov byte [TT_SKIP], 1
    # Check if renderable Hangul (lead 0xB0-0xC8)
    c += b'\x80\xFB\xB0'                            # cmp bl, 0xB0
    skip_dbcs_off1 = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'                  # jb .skip_dbcs
    c += b'\x80\xFB\xC8'                            # cmp bl, 0xC8
    skip_dbcs_off2 = len(c)
    c += b'\x0F\x87' + b'\0\0\0\0'                  # ja .skip_dbcs

    # ---- 5. RENDER KOREAN GLYPH ----
    c += b'\x60'                                     # pushad
    # Default advance in case render fails early
    c += b'\xC7\x05' + le32(TT_ADV) + le32(14)     # mov [TT_ADV], 14

    # ---- GAME WORLD EVENT SKIP ----
    # Game world event notifications: param3==1 && y>10 && y<400 && x<50
    # tooltip_draw has only 4 params (string, x, y, param3) - no param4!
    # Skip Korean rendering to prevent duplicate text on game screen
    # (popup shows the same text separately, so no info lost)
    c += b'\x8B\x7C\x24\x44'                        # mov edi, [esp+0x44] (param3)
    c += b'\x83\xFF\x01'                             # cmp edi, 1
    gw_cont1 = len(c)
    c += b'\x0F\x85' + b'\0\0\0\0'                  # jne .gw_continue (near)
    c += b'\x8B\x7C\x24\x40'                        # mov edi, [esp+0x40] (y)
    c += b'\x83\xFF\x0A'                             # cmp edi, 10
    gw_cont2 = len(c)
    c += b'\x0F\x8E' + b'\0\0\0\0'                  # jle .gw_continue
    c += b'\x81\xFF\x90\x01\x00\x00'                # cmp edi, 400
    gw_cont3 = len(c)
    c += b'\x0F\x8D' + b'\0\0\0\0'                  # jge .gw_continue
    c += b'\x8B\x7C\x24\x3C'                        # mov edi, [esp+0x3C] (x param)
    c += b'\x83\xFF\x32'                             # cmp edi, 50
    gw_cont4 = len(c)
    c += b'\x0F\x8D' + b'\0\0\0\0'                  # jge .gw_continue
    # All conditions met → game world event, skip rendering
    gw_skip = len(c)
    c += b'\xE9' + b'\0\0\0\0'                      # jmp .render_skip (patched later)
    # .gw_continue:
    gw_continue = len(c)
    for gw_off in [gw_cont1, gw_cont2, gw_cont3, gw_cont4]:
        struct.pack_into('<i', c, gw_off+2, gw_continue-(gw_off+6))

    # Glyph index = (lead-0xB0)*94 + (trail-0xA1)
    c += b'\x0F\xB6\xC3'                            # movzx eax, bl (lead)
    c += b'\x0F\xB6\x0E'                            # movzx ecx, byte [esi] (trail)
    c += b'\x2D' + le32(0xB0)                       # sub eax, 0xB0
    c += b'\x6B\xC0\x5E'                            # imul eax, 94
    c += b'\x81\xE9' + le32(0xA1)                   # sub ecx, 0xA1
    c += b'\x01\xC8'                                # add eax, ecx

    c += b'\x3D' + le32(2350)                        # cmp eax, 2350
    sk1 = len(c)
    c += b'\x0F\x83' + b'\0\0\0\0'                  # jae .render_skip

    # Validate pixel buffer
    c += b'\x8B\x35' + le32(PIXEL_BUF_PTR)         # mov esi, [pixel_buf]
    c += b'\x81\xFE\x00\x00\x01\x00'                # cmp esi, 0x10000
    sk2 = len(c)
    c += b'\x0F\x82' + b'\0\0\0\0'                  # jb .render_skip

    # Validate surface dimensions
    c += b'\x8B\x3D' + le32(0xF2A6A0)              # mov edi, [surf_width]
    c += b'\x85\xFF'                                # test edi, edi
    sk_w = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'                  # jz .render_skip
    # Offscreen skip REMOVED — was causing custom adventure Korean to be invisible
    # Game world duplicate prevention is handled by param3 check instead
    c += b'\x8B\x3D' + le32(0xF2A69C)              # mov edi, [surf_height]
    c += b'\x85\xFF'
    sk_h = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'
    c += b'\x8B\x3D' + le32(PITCH_PTR)             # mov edi, [pitch]
    c += b'\x85\xFF'
    sk_p = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'

    # Bounds check: x+16 <= width
    # After pushad: [esp+0x08] = saved EBP = current x position
    c += b'\x8B\x7C\x24\x08'                        # mov edi, [esp+8] (saved ebp=x)
    c += b'\x83\xC7\x10'                            # add edi, 16
    c += b'\x3B\x3D' + le32(0xF2A6A0)              # cmp edi, [surf_width]
    sk3 = len(c)
    c += b'\x0F\x8F' + b'\0\0\0\0'                  # jg .render_skip

    # Bounds check: y+16 <= height
    # After pushad(+32) + tooltip's 5 pushes: y = [esp+0x40]
    c += b'\x8B\x7C\x24\x40'                        # mov edi, [esp+0x40] (y param)
    c += b'\x83\xC7\x10'                            # add edi, 16
    c += b'\x3B\x3D' + le32(0xF2A69C)              # cmp edi, [surf_height]
    sk4 = len(c)
    c += b'\x0F\x8F' + b'\0\0\0\0'                  # jg .render_skip

    # ---- FONT SIZE SELECTION (sprite height based) ----
    c += b'\x8B\x1D' + le32(0xEF8C9C)              # mov ebx, [font_base_global]
    c += b'\x8B\x3D' + le32(SPRITE_RECORDS_PTR)    # mov edi, [records_base]
    c += b'\x85\xFF'
    ul1 = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'                  # jz .use_large
    c += b'\x85\xDB'
    ul2 = len(c)
    c += b'\x0F\x84' + b'\0\0\0\0'                  # jz .use_large
    c += b'\x6B\xDB\x48'                            # imul ebx, ebx, 72
    c += b'\x0F\xBF\x5C\x1F\x16'                    # movsx ebx, word[edi+ebx+0x16]
    c += b'\x83\xFB\x0D'                            # cmp ebx, 13
    ul3 = len(c)
    c += b'\x0F\x8F' + b'\0\0\0\0'                  # jg .use_large

    # Small font path (sprite_h <= 13)
    c += b'\x8B\x35' + le32(PIXEL_BUF_PTR)
    c += b'\xC1\xE0\x05'                            # shl eax, 5 (glyph_idx * 32)
    c += b'\xBA' + le32(font_small_va)
    c += b'\x01\xC2'                                # add edx, eax
    c += b'\xC7\x05' + le32(TT_ADV) + le32(9)
    c += b'\xC7\x05' + le32(TT_YOFF) + le32(1)     # small: y_offset=1 (tooltip has no y-3)
    c += b'\xBB\x0B\x00\x00\x00'                    # mov ebx, 11 (rows)
    fd_off = len(c)
    c += b'\xE9' + b'\0\0\0\0'                      # jmp .font_done

    # .use_large
    use_large = len(c)
    struct.pack_into('<i', c, ul1+2, use_large-(ul1+6))
    struct.pack_into('<i', c, ul2+2, use_large-(ul2+6))
    struct.pack_into('<i', c, ul3+2, use_large-(ul3+6))
    c += b'\x8B\x35' + le32(PIXEL_BUF_PTR)
    c += b'\xC1\xE0\x05'
    c += b'\xBA' + le32(font_large_va)
    c += b'\x01\xC2'
    c += b'\xC7\x05' + le32(TT_ADV) + le32(14)
    c += b'\xC7\x05' + le32(TT_YOFF) + le32(0)     # large: y_offset=0 (tooltip has no y-3)
    c += b'\xBB\x10\x00\x00\x00'                    # mov ebx, 16 (rows)

    # .font_done
    font_done = len(c)
    struct.pack_into('<i', c, fd_off+1, font_done-(fd_off+5))

    # Pixel destination = pixel_buf + (y - y_offset) * pitch + x * 2
    c += b'\x8B\x44\x24\x40'                        # mov eax, [esp+0x40] (y)
    c += b'\x2B\x05' + le32(TT_YOFF)               # sub eax, [TT_YOFF]
    c += b'\x78\x02'                                # js +2 (clamp to 0)
    c += b'\xEB\x02'                                # jmp +2
    c += b'\x33\xC0'                                # xor eax, eax
    c += b'\x0F\xAF\x05' + le32(PITCH_PTR)         # imul eax, [pitch]
    c += b'\x01\xC6'                                # add esi, eax
    c += b'\x8B\x7C\x24\x08'                        # mov edi, [esp+8] (saved ebp=x)
    c += b'\x8D\x34\x7E'                            # lea esi, [esi+edi*2]

    # Render 1bpp glyph rows (ebx=row count, edx=glyph data, esi=dest)
    c += b'\x89\xD9'                                # mov ecx, ebx
    rr = len(c)
    c += b'\x0F\xB6\x02'                            # movzx eax, [edx]
    c += b'\xC1\xE0\x08'                            # shl eax, 8
    c += b'\x0F\xB6\x5A\x01'                        # movzx ebx, [edx+1]
    c += b'\x09\xD8'                                # or eax, ebx
    c += b'\x8B\xFE'                                # mov edi, esi
    c += b'\xBB\x10\x00\x00\x00'                    # mov ebx, 16 (columns)
    il = len(c)
    c += b'\xA9\x00\x80\x00\x00'                    # test eax, 0x8000
    c += b'\x74\x05'                                # jz +5
    c += b'\x66\xC7\x07\xFF\xFF'                    # mov word [edi], 0xFFFF (white pixel)
    c += b'\xD1\xE0'                                # shl eax, 1
    c += b'\x83\xC7\x02'                            # add edi, 2
    c += b'\x4B'                                    # dec ebx
    c += b'\x75' + struct.pack('b', il - (len(c) + 2))
    c += b'\x83\xC2\x02'                            # add edx, 2
    c += b'\x03\x35' + le32(PITCH_PTR)              # add esi, [pitch]
    c += b'\x49'                                    # dec ecx
    c += b'\x75' + struct.pack('b', rr - (len(c) + 2))

    # .render_skip — resolve all skip jumps
    sk = len(c)
    for s in [sk1, sk2, sk_w, sk_h, sk_p, sk3, sk4]:
        struct.pack_into('<i', c, s+2, sk-(s+6))
    # gw_skip is a JMP (E9), offset at +1 not +2
    struct.pack_into('<i', c, gw_skip+1, sk-(gw_skip+5))

    c += b'\x61'                                     # popad
    c += b'\xA1' + le32(TT_ADV)                     # mov eax, [TT_ADV]
    c += b'\xE9' + rel32(P + len(c) + 5, TT_ADVANCE)

    # .skip_dbcs — DBCS pair but not renderable Hangul
    skip_dbcs = len(c)
    struct.pack_into('<i', c, skip_dbcs_off1+2, skip_dbcs-(skip_dbcs_off1+6))
    struct.pack_into('<i', c, skip_dbcs_off2+2, skip_dbcs-(skip_dbcs_off2+6))
    c += b'\xB8\x06\x00\x00\x00'                    # mov eax, 6
    c += b'\xE9' + rel32(P + len(c) + 5, TT_ADVANCE)

    # .skip_single — single high byte (no valid DBCS trail)
    skip_single = len(c)
    struct.pack_into('<i', c, skip_single_off+2, skip_single-(skip_single_off+6))
    c += b'\xB8\x06\x00\x00\x00'                    # mov eax, 6
    c += b'\xE9' + rel32(P + len(c) + 5, TT_ADVANCE)

    return bytes(c)


def add_pe_section(data, name, sdata, chars=0xE0000060):
    """Add a new PE section. Returns (data, relative_va, file_offset)."""
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    nsec = struct.unpack_from('<H', data, pe+6)[0]
    ohsz = struct.unpack_from('<H', data, pe+0x14)[0]
    ss = pe + 0x18 + ohsz
    ls = ss + (nsec-1)*40
    lva = struct.unpack_from('<I', data, ls+12)[0]
    lvs = struct.unpack_from('<I', data, ls+8)[0]
    lro = struct.unpack_from('<I', data, ls+20)[0]
    lrs = struct.unpack_from('<I', data, ls+16)[0]
    fa = struct.unpack_from('<I', data, pe+0x3C)[0]
    sa = struct.unpack_from('<I', data, pe+0x38)[0]
    nva = (lva+lvs+sa-1) & ~(sa-1)
    nro = (lro+lrs+fa-1) & ~(fa-1)
    nrs = (len(sdata)+fa-1) & ~(fa-1)
    nvs = (len(sdata)+sa-1) & ~(sa-1)
    hdr = name.encode('ascii')[:8].ljust(8, b'\0')
    hdr += struct.pack('<IIIIIIHHI', nvs, nva, nrs, nro, 0, 0, 0, 0, chars)
    d = bytearray(data)
    struct.pack_into('<H', d, pe+6, nsec+1)
    struct.pack_into('<I', d, pe+0x50, nva+nvs)
    nso = ss + nsec*40
    d[nso:nso+40] = hdr
    if len(d) < nro: d += b'\0' * (nro - len(d))
    d += sdata + b'\0' * (nrs - len(sdata))
    return bytes(d), nva, nro


def patch_exe(inp, outp, fl, fs):
    print(f"Reading {inp}...")
    with open(inp, 'rb') as f: data = f.read()
    osz = len(data)
    assert data[PP1_FILE:PP1_FILE+6] == PP1_ORIG, "PP1 mismatch"
    assert data[PP3_FILE:PP3_FILE+5] == PP3_ORIG, "PP3 mismatch"
    assert data[PP4_FILE:PP4_FILE+9] == PP4_ORIG, "PP4 mismatch"
    assert data[PP5_FILE:PP5_FILE+5] == PP5_ORIG, "PP5 mismatch"
    assert data[PP6_FILE:PP6_FILE+5] == PP6_ORIG, "PP6 mismatch"
    # PP7 adventure bitmap font — NOT NEEDED when glyph table is preserved
    # assert data[PP7_FILE:PP7_FILE+6] == PP7_ORIG, "PP7 mismatch"
    with open(fl, 'rb') as f: font_l = f.read()
    with open(fs, 'rb') as f: font_s = f.read()
    assert len(font_l) == KFONT_TOTAL_SIZE
    # Load ASCII font files
    ascii_l_path = os.path.join(os.path.dirname(fl), 'kfont_ascii_large.bin')
    ascii_s_path = os.path.join(os.path.dirname(fs), 'kfont_ascii_small.bin')
    with open(ascii_l_path, 'rb') as f: ascii_l = f.read()
    with open(ascii_s_path, 'rb') as f: ascii_s = f.read()
    assert len(ascii_l) == ASCII_TOTAL_SIZE
    # Load title font
    title_path = os.path.join(os.path.dirname(fl), 'kfont_title_large.bin')
    with open(title_path, 'rb') as f: title_font = f.read()
    assert len(title_font) == TITLE_FONT_SIZE

    # Build .krfnt section: [code] [korean_large] [korean_small] [ascii_l] [ascii_s] [title]
    sec = bytearray(CODE_SIZE)
    struct.pack_into('<I', sec, 0, 1)           # magic
    struct.pack_into('<I', sec, 4, CODE_SIZE)   # font data offset
    sec = bytes(sec) + font_l + font_s + ascii_l + ascii_s + title_font

    data, sva, sec_file_off = add_pe_section(data, '.krfnt', sec)
    data = bytearray(data)

    sec_va = BASE_VA + sva
    globals_va = sec_va
    handler_va = sec_va + HANDLER_OFF
    gcw_va = sec_va + GCW_OFF
    ww_va = sec_va + WW_OFF
    font_large_va = sec_va + CODE_SIZE
    font_small_va = font_large_va + KFONT_TOTAL_SIZE
    ascii_large_va = font_small_va + KFONT_TOTAL_SIZE
    ascii_small_va = ascii_large_va + ASCII_TOTAL_SIZE
    title_font_va = ascii_small_va + ASCII_TOTAL_SIZE
    csw_va = sec_va + CSW_OFF
    tt_va = sec_va + TT_OFF
    pw_va = sec_va + PW_OFF
    ab_va = sec_va + AB_OFF

    print(f"  Section VA: 0x{sec_va:08X}")
    print(f"  Handler VA: 0x{handler_va:08X}")
    print(f"  TT Handler: 0x{tt_va:08X}")
    print(f"  PW Handler: 0x{pw_va:08X}")
    print(f"  Font Large: 0x{font_large_va:08X}")
    print(f"  Font Small: 0x{font_small_va:08X}")
    print(f"  ASCII Large: 0x{ascii_large_va:08X}")
    print(f"  ASCII Small: 0x{ascii_small_va:08X}")
    print(f"  Title Font:  0x{title_font_va:08X}")

    # Build handlers with .krfnt section VAs
    h1 = build_korean_handler(handler_va, font_large_va, font_small_va, globals_va,
                              title_font_va=title_font_va)
    h2 = build_gcw_handler(gcw_va, globals_va)
    h3 = build_ww_handler(ww_va)
    h4 = build_csw_handler(csw_va, globals_va)
    h5 = build_tt_handler(tt_va, font_large_va, font_small_va, globals_va)
    h6 = build_pw_handler(pw_va)
    # h7 = build_ab_handler(ab_va, font_large_va, font_small_va, globals_va)

    print(f"  Korean handler: {len(h1)} bytes")
    print(f"  GCW handler:    {len(h2)} bytes")
    print(f"  WW handler:     {len(h3)} bytes")
    print(f"  CSW handler:    {len(h4)} bytes")
    print(f"  TT handler:     {len(h5)} bytes")
    print(f"  PW handler:     {len(h6)} bytes")
    # print(f"  AB handler:     {len(h7)} bytes")

    # Write handlers into .krfnt section
    data[sec_file_off + HANDLER_OFF : sec_file_off + HANDLER_OFF + len(h1)] = h1
    data[sec_file_off + GCW_OFF : sec_file_off + GCW_OFF + len(h2)] = h2
    data[sec_file_off + WW_OFF : sec_file_off + WW_OFF + len(h3)] = h3
    data[sec_file_off + CSW_OFF : sec_file_off + CSW_OFF + len(h4)] = h4
    data[sec_file_off + TT_OFF : sec_file_off + TT_OFF + len(h5)] = h5
    data[sec_file_off + PW_OFF : sec_file_off + PW_OFF + len(h6)] = h6

    # Patch jump points to .krfnt handlers
    data[PP1_FILE:PP1_FILE+6] = jmp32(PP1_VA, handler_va) + b'\x90'
    data[PP2_FILE:PP2_FILE+6] = jmp32(PP2_VA, gcw_va) + b'\x90'
    data[PP3_FILE:PP3_FILE+5] = jmp32(PP3_VA, ww_va)
    # PP4: calc_string_width - replace 9 bytes with JMP + 4 NOPs
    data[PP4_FILE:PP4_FILE+9] = jmp32(PP4_VA, csw_va) + b'\x90\x90\x90\x90'
    # PP5: tooltip_draw - replace 5 bytes with JMP
    data[PP5_FILE:PP5_FILE+5] = jmp32(PP5_VA, tt_va)
    # PP6: popup word width DBCS - replace 5 bytes with JMP
    data[PP6_FILE:PP6_FILE+5] = jmp32(PP6_VA, pw_va)
    # PP7 removed — not needed when glyph table is preserved

    # Glyph table: DO NOT zero out! Original Latin-1 extended glyphs are needed
    # for custom adventure bitmap font rendering. PP1 already intercepts all
    # bytes >= 0x80 before the glyph table is checked in text_draw_loop,
    # so zeroing is unnecessary and causes side effects.
    print(f"  Glyph table: preserved (PP1 handles high bytes before glyph check)")
    print(f"  Patches applied (7 hooks)")

    with open(outp, 'wb') as f: f.write(data)
    print(f"  Output: {outp} ({len(data)} bytes, +{len(data)-osz})")
    return True


def main():
    gd = r'C:\Program Files (x86)\Steam\steamapps\common\Zeus + Poseidon'
    fd = r'C:\Users\HOME\dll_build'
    p = argparse.ArgumentParser()
    p.add_argument('--input', default=os.path.join(gd, 'Zeus.exe'))
    p.add_argument('--output', default=os.path.join(gd, 'Zeus_kr.exe'))
    p.add_argument('--font-large', default=os.path.join(fd, 'kfont_large_new.bin'))
    p.add_argument('--font-small', default=os.path.join(fd, 'kfont_small_new.bin'))
    a = p.parse_args()
    sys.exit(0 if patch_exe(a.input, a.output, a.font_large, a.font_small) else 1)

if __name__ == '__main__':
    main()
