"""
KALKULATOR GEOMETRI TIKUNGAN JALAN  (FC - SCS - SS)
Streamlit + ezdxf + pandas/openpyxl

Jalankan :  streamlit run app.py
Install  :  pip install streamlit ezdxf pandas numpy openpyxl matplotlib
"""
import io
import math
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st
import ezdxf

try:
    from ezdxf.enums import TextEntityAlignment

    def _align(a):
        return TextEntityAlignment[a]
except Exception:  # ezdxf versi lama
    def _align(a):
        return a

# =============================================================================
#  KONSTANTA STANDAR
# =============================================================================
# Radius minimum tikungan FC tanpa lengkung peralihan (Bina Marga / TPGJAK)
RMIN_FC = {120: 2500, 100: 1500, 80: 900, 60: 500, 50: 350, 40: 250, 30: 130, 20: 60}
# Jarak pandang mendahului minimum (TPGJAK No. 038/TBM/1997)
JPM_STD = {120: 800, 100: 670, 80: 550, 60: 350, 50: 250, 40: 200, 30: 150, 20: 100}
# Jarak pandang henti minimum (Bina Marga)
JPH_STD = {120: 250, 100: 175, 80: 120, 60: 75, 50: 55, 40: 40, 30: 27, 20: 16}

D2R = math.pi / 180.0
R2D = 180.0 / math.pi


def _nearest(tabel, v):
    return tabel[min(tabel, key=lambda k: abs(k - v))]


def fmt_sta(x):
    """Format stasioning:  385.0 -> 0+385.00"""
    return f"{int(x // 1000)}+{x % 1000:06.2f}"


def baris(nama, simbol, rumus, nilai, satuan):
    return {"Parameter": nama, "Simbol": simbol, "Rumus": rumus, "Nilai": nilai, "Satuan": satuan}


# =============================================================================
#  PERHITUNGAN DASAR
# =============================================================================
def f_gesek(vr):
    """Koefisien gesek melintang maksimum."""
    return -0.00065 * vr + 0.192 if vr < 80 else -0.00125 * vr + 0.24


def hitung_dasar(P):
    f = f_gesek(P["Vr"])
    rmin = P["Vr"] ** 2 / (127 * (P["emax"] + f))
    return {"f": f, "Rmin": rmin, "R_ok": P["Rc"] >= rmin, "RminFC": _nearest(RMIN_FC, P["Vr"])}


def ls_kriteria(P):
    """Empat kriteria panjang lengkung peralihan minimum (sesuai laporan)."""
    vr, R = P["Vr"], P["Rc"]
    re = P["re"] if P["re"] > 0 else (0.025 if vr <= 70 else 0.035)
    k1 = 0.0214 * vr ** 3 / (R * P["C1"])
    k2 = vr / 3.6 * P["T"]
    k3 = 0.022 * vr ** 3 / (R * P["Cc"]) - 2.727 * vr * P["emax"] / P["Cc"]
    k4 = (P["emax"] - P["en"]) * vr / (3.6 * re)
    return k1, k2, k3, k4, re


# ----------------------------------------------------------------- FULL CIRCLE
def hitung_fc(P, sta_pi):
    R, d = P["Rc"], P["delta"]
    dasar = hitung_dasar(P)
    Lc = d * math.pi * R / 180
    Tc = R * math.tan(d / 2 * D2R)
    Ec = Tc * math.tan(d / 4 * D2R)
    v = dict(R=R, delta=d, Lc=Lc, Tc=Tc, Ec=Ec)
    ok = dasar["R_ok"]
    pesan = []
    if not dasar["R_ok"]:
        pesan.append(f"R = {R:.2f} m < Rmin = {dasar['Rmin']:.2f} m (tidak memenuhi).")
    if R < dasar["RminFC"]:
        pesan.append(
            f"R < {dasar['RminFC']} m (R minimum FC tanpa lengkung peralihan untuk Vr ini). "
            "FC tetap dihitung, tetapi sebaiknya gunakan SCS/SS."
        )
    rows = [
        baris("Koefisien gesek", "f", "-0,00065·Vr + 0,192 (Vr<80); -0,00125·Vr + 0,24", dasar["f"], "-"),
        baris("Radius minimum", "Rmin", "Vr² / [127(emax + f)]", dasar["Rmin"], "m"),
        baris("Cek radius rencana", "Rc ≥ Rmin", f"{R:g} ≥ {dasar['Rmin']:.2f}", "OK" if dasar["R_ok"] else "TIDAK OK", "-"),
        baris("Panjang busur lingkaran", "Lc", "Δ·2π·R / 360", Lc, "m"),
        baris("Jarak TC ke PI", "Tc", "R·tan(Δ/2)", Tc, "m"),
        baris("Jarak PI ke busur", "Ec", "Tc·tan(Δ/4)", Ec, "m"),
    ]
    sta = [
        ("TC (awal tikungan)", sta_pi - Tc),
        ("PI", sta_pi),
        ("CT (akhir tikungan)", sta_pi - Tc + Lc),
    ]
    return dict(tipe="FC", ok=ok, pesan=pesan, v=v, rows=rows, sta=sta)


# ------------------------------------------------------- SPIRAL-CIRCLE-SPIRAL
def _spiral_umum(R, d, Ls, tipe, P, sta_pi):
    """Rumus bersama SCS & SS untuk Ls dan theta_s yang sudah diketahui."""
    ths = 90 * Ls / (math.pi * R) if tipe == "SCS" else d / 2
    thc = d - 2 * ths
    Lc = thc * math.pi * R / 180 if thc > 0 else 0.0
    Xc = Ls - Ls ** 3 / (40 * R ** 2)
    Yc = Ls ** 2 / (6 * R)
    p = Yc - R * (1 - math.cos(ths * D2R))
    k = Xc - R * math.sin(ths * D2R)
    Es = (R + p) / math.cos(d / 2 * D2R) - R
    Ts = (R + p) * math.tan(d / 2 * D2R) + k
    Ltot = Lc + 2 * Ls
    return dict(R=R, delta=d, Ls=Ls, ths=ths, thc=thc, Lc=Lc, Xc=Xc, Yc=Yc, P=p, K=k, Es=Es, Ts=Ts, Ltot=Ltot)


def hitung_scs(P, sta_pi):
    R, d = P["Rc"], P["delta"]
    dasar = hitung_dasar(P)
    k1, k2, k3, k4, re = ls_kriteria(P)
    ls_min = max(k1, k2, k3, k4)
    ls = P["Ls_rencana"] if P["Ls_rencana"] > 0 else math.ceil(ls_min / 5) * 5
    v = _spiral_umum(R, d, ls, "SCS", P, sta_pi)
    pesan, ok = [], dasar["R_ok"]
    if not dasar["R_ok"]:
        pesan.append(f"R = {R:.2f} m < Rmin = {dasar['Rmin']:.2f} m (tidak memenuhi).")
    if ls < ls_min:
        pesan.append(f"Ls rencana {ls:.2f} m < Ls min {ls_min:.2f} m.")
        ok = False
    if v["thc"] <= 0:
        pesan.append(f"θc = {v['thc']:.2f}° ≤ 0 → SCS tidak bisa dibentuk, gunakan SS.")
        ok = False
    elif v["Lc"] < 20:
        pesan.append(f"Lc = {v['Lc']:.2f} m < 20 m → disarankan memakai SS.")
    rows = [
        baris("Koefisien gesek", "f", "-0,00065·Vr + 0,192 (Vr<80); -0,00125·Vr + 0,24", dasar["f"], "-"),
        baris("Radius minimum", "Rmin", "Vr² / [127(emax + f)]", dasar["Rmin"], "m"),
        baris("Ls min kriteria 1 (Shortt)", "Ls₁", "0,0214·Vr³ / (R·C)", k1, "m"),
        baris("Ls min kriteria 2 (waktu tempuh)", "Ls₂", "Vr/3,6 · T", k2, "m"),
        baris("Ls min kriteria 3 (gaya sentrifugal)", "Ls₃", "0,022·Vr³/(R·C) − 2,727·Vr·e/C", k3, "m"),
        baris("Ls min kriteria 4 (landai relatif)", "Ls₄", "(emax − en)·Vr / (3,6·re)", k4, "m"),
        baris("Ls minimum (terbesar)", "Ls min", "max(Ls₁..Ls₄)", ls_min, "m"),
        baris("Ls rencana", "Ls", "dibulatkan ke atas kelipatan 5" if P["Ls_rencana"] <= 0 else "input", ls, "m"),
        baris("Sudut spiral", "θs", "90·Ls / (π·R)", v["ths"], "°"),
        baris("Sudut busur lingkaran", "θc", "Δ − 2θs", v["thc"], "°"),
        baris("Panjang busur lingkaran", "Lc", "θc/360 · 2πR", v["Lc"], "m"),
        baris("Panjang total tikungan", "Ltot", "Lc + 2Ls", v["Ltot"], "m"),
        baris("Absis SC", "Xc", "Ls − Ls³/(40R²)", v["Xc"], "m"),
        baris("Ordinat SC", "Yc", "Ls²/(6R)", v["Yc"], "m"),
        baris("Pergeseran busur", "P", "Yc − R(1 − cos θs)", v["P"], "m"),
        baris("Absis pusat busur", "K", "Xc − R·sin θs", v["K"], "m"),
        baris("Jarak luar PI ke busur", "Es", "(R+P)/cos(Δ/2) − R", v["Es"], "m"),
        baris("Jarak TS ke PI", "Ts", "(R+P)·tan(Δ/2) + K", v["Ts"], "m"),
    ]
    ts = sta_pi - v["Ts"]
    sta = [
        ("TS (awal spiral)", ts),
        ("SC (spiral → busur)", ts + ls),
        ("PI", sta_pi),
        ("CS (busur → spiral)", ts + ls + v["Lc"]),
        ("ST (akhir spiral)", ts + 2 * ls + v["Lc"]),
    ]
    return dict(tipe="SCS", ok=ok, pesan=pesan, v=v, rows=rows, sta=sta)


# ------------------------------------------------------------- SPIRAL-SPIRAL
def hitung_ss(P, sta_pi):
    R, d = P["Rc"], P["delta"]
    dasar = hitung_dasar(P)
    k1, k2, k3, k4, re = ls_kriteria(P)
    ls_min = max(k1, k2, k3, k4)
    ths = d / 2
    ls = ths * math.pi * R / 90  # geometri SS: Ls ditentukan oleh Δ dan R
    v = _spiral_umum(R, d, ls, "SS", P, sta_pi)
    v["Lc"] = 0.0
    v["thc"] = 0.0
    v["Ltot"] = 2 * ls
    pesan, ok = [], dasar["R_ok"]
    if not dasar["R_ok"]:
        pesan.append(f"R = {R:.2f} m < Rmin = {dasar['Rmin']:.2f} m (tidak memenuhi).")
    if ls < ls_min:
        pesan.append(f"Ls = {ls:.2f} m < Ls min = {ls_min:.2f} m. Perbesar Δ / perkecil R, atau pakai FC/SCS.")
        ok = False
    rows = [
        baris("Koefisien gesek", "f", "-0,00065·Vr + 0,192 (Vr<80); -0,00125·Vr + 0,24", dasar["f"], "-"),
        baris("Radius minimum", "Rmin", "Vr² / [127(emax + f)]", dasar["Rmin"], "m"),
        baris("Sudut spiral", "θs", "Δ/2", ths, "°"),
        baris("Panjang spiral", "Ls", "θs·π·R / 90", ls, "m"),
        baris("Ls minimum (terbesar 4 kriteria)", "Ls min", "max(Ls₁..Ls₄)", ls_min, "m"),
        baris("Cek Ls ≥ Ls min", "-", f"{ls:.2f} ≥ {ls_min:.2f}", "OK" if ls >= ls_min else "TIDAK OK", "-"),
        baris("Absis SS", "Xs", "Ls − Ls³/(40R²)", v["Xc"], "m"),
        baris("Ordinat SS", "Ys", "Ls²/(6R)", v["Yc"], "m"),
        baris("Pergeseran busur", "P", "Ys − R(1 − cos θs)", v["P"], "m"),
        baris("Absis pusat busur", "K", "Xs − R·sin θs", v["K"], "m"),
        baris("Panjang total tikungan", "Ltot", "2·Ls", v["Ltot"], "m"),
        baris("Jarak luar PI ke busur", "Es", "(R+P)/cos(Δ/2) − R", v["Es"], "m"),
        baris("Jarak TS ke PI", "Ts", "(R+P)·tan(Δ/2) + K", v["Ts"], "m"),
    ]
    ts = sta_pi - v["Ts"]
    sta = [("TS (awal spiral)", ts), ("SS (titik spiral-spiral)", ts + ls), ("PI", sta_pi), ("ST (akhir spiral)", ts + 2 * ls)]
    return dict(tipe="SS", ok=ok, pesan=pesan, v=v, rows=rows, sta=sta)


def rekomendasi(P, hasil):
    """Saran jenis tikungan: FC bila R besar, SCS bila Lc ≥ 20 m, selain itu SS."""
    dasar = hitung_dasar(P)
    if P["Rc"] >= dasar["RminFC"] and hasil["FC"]["ok"]:
        return "FC"
    scs = hasil["SCS"]
    if scs["v"]["thc"] > 0 and scs["v"]["Lc"] >= 20 and scs["ok"]:
        return "SCS"
    return "SS"


# =============================================================================
#  PELEBARAN PERKERASAN
# =============================================================================
def hitung_pelebaran(P, R, vr):
    p, A, b, n, Bn, kz = P["p"], P["A"], P["b"], P["n"], P["Bn"], P["kz"]
    C = Bn / 2 - b
    b2 = R - math.sqrt(R ** 2 - p ** 2)
    bp = b + b2
    Td = math.sqrt(R ** 2 + A * (2 * p + A)) - R
    Z = kz * vr / math.sqrt(R)
    k_td = n + 1 if P["td_n_plus_1"] else n - 1  # laporan memakai (n+1); buku Bina Marga (n-1)
    Bt = n * (bp + C) + k_td * Td + Z
    db = Bt - Bn
    rows = [
        baris("Clearance samping", "C", "Bn/2 − b", C, "m"),
        baris("Off-tracking kendaraan", "b''", "R − √(R² − p²)", b2, "m"),
        baris("Lebar kendaraan di tikungan", "b'", "b + b''", bp, "m"),
        baris("Tonjolan depan kendaraan", "Td", "√(R² + A(2p + A)) − R", Td, "m"),
        baris("Faktor kesulitan mengemudi", "Z", f"{kz:g}·Vr / √R", Z, "m"),
        baris("Lebar perkerasan di tikungan", "Bt", "n(b'+C) + (n+1)·Td + Z" if P["td_n_plus_1"] else "n(b'+C) + (n−1)·Td + Z", Bt, "m"),
        baris("Kebutuhan pelebaran total", "Δb", "Bt − Bn", db, "m"),
        baris("Pelebaran per sisi", "Δb/2", "Δb / 2", db / 2, "m"),
    ]
    return dict(C=C, b2=b2, bp=bp, Td=Td, Z=Z, Bt=Bt, db=max(db, 0.0), db_raw=db, rows=rows)


# =============================================================================
#  JARAK PANDANG
# =============================================================================
def hitung_jph(vr, t, a, G):
    """G dalam desimal (+ tanjakan, - turunan)."""
    d1 = vr * t / 3.6
    d2 = vr ** 2 / (2 * 3.6 ** 2 * 9.81 * (a / 9.81 + G))
    return d1 + d2, d1, d2


def hitung_jpm(vr, m, d3):
    T1 = 2.12 + 0.026 * vr
    T2 = 6.56 + 0.048 * vr
    a = 2.052 + 0.0036 * vr
    d1 = 0.278 * T1 * (vr - m + a * T1 / 2)
    d2 = 0.278 * vr * T2
    d4 = 2 / 3 * d2
    return dict(T1=T1, T2=T2, a=a, d1=d1, d2=d2, d3=d3, d4=d4, JPM=d1 + d2 + d3 + d4)


# =============================================================================
#  GEOMETRI (koordinat lokal, satuan meter)
#  TS/TC di (0,0); tangen awal sepanjang +x; tikungan ke KIRI sebesar Δ.
# =============================================================================
def _spiral_pts(Ls, R, n=40):
    l = np.linspace(0, Ls, n)
    x = l - l ** 5 / (40 * R ** 2 * Ls ** 2)
    y = l ** 3 / (6 * R * Ls)
    return np.column_stack([x, y])


def _refleksi(pts, p0, u):
    v = np.asarray(pts, float) - p0
    dot = (v @ u)[..., None] if v.ndim > 1 else v @ u
    return p0 + 2 * dot * u - v


def bangun_geometri(hasil, ext, taper_fc=20.0):
    tipe, v = hasil["tipe"], hasil["v"]
    R, d = v["R"], v["delta"]
    cd, sd = math.cos(d * D2R), math.sin(d * D2R)
    g = {"tipe": tipe}
    if tipe == "FC":
        Ts = v["Tc"]
        O = np.array([0.0, R])
        PI = np.array([Ts, 0.0])
        ST = PI + Ts * np.array([cd, sd])
        a0, a1 = 270.0, 270.0 + d
        th = np.linspace(a0, a1, max(8, int(d / 2) + 8)) * D2R
        arc = O + R * np.column_stack([np.cos(th), np.sin(th)])
        s1 = s2 = None
        g.update(TC=np.array([0.0, 0.0]), CT=ST)
        curva = arc
        tcur = np.ones(len(arc))
    else:
        Ls, ths, thc, P_, K = v["Ls"], v["ths"], v["thc"], v["P"], v["K"]
        Ts = v["Ts"]
        O = np.array([K, R + P_])
        PI = np.array([Ts, 0.0])
        s1 = _spiral_pts(Ls, R)
        ts1 = np.linspace(0, 1, len(s1))
        u = (O - PI) / np.linalg.norm(O - PI)
        s2 = _refleksi(s1, PI, u)[::-1]
        ST = _refleksi(np.array([0.0, 0.0]), PI, u)
        SC = s1[-1]
        CS = s2[0]
        if thc > 1e-6:
            a0, a1 = 270.0 + ths, 270.0 + ths + thc
            th = np.linspace(a0, a1, max(8, int(thc / 2) + 8)) * D2R
            arc = O + R * np.column_stack([np.cos(th), np.sin(th)])
            curva = np.vstack([s1, arc[1:-1], s2])
            tcur = np.concatenate([ts1, np.ones(len(arc) - 2), ts1[::-1]])
        else:
            a0 = a1 = None
            arc = None
            curva = np.vstack([s1, s2[1:]])
            tcur = np.concatenate([ts1, ts1[::-1][1:]])
        g.update(TS=np.array([0.0, 0.0]), ST=ST, SC=SC, CS=CS)
    g.update(O=O, PI=PI, ST=ST, Ts=Ts, arc_ang=(a0, a1) if tipe == "FC" or v["thc"] > 1e-6 else None)

    # garis tengah lengkap (dengan perpanjangan tangen) + parameter pelebaran t (0..1)
    dirB = np.array([cd, sd])
    if tipe == "FC":  # pelebaran FC dibuat bertahap pada tangen sepanjang taper_fc
        pre = np.array([[-ext, 0.0], [-taper_fc, 0.0]])
        tpre = np.array([0.0, 0.0])
        post = np.array([ST + taper_fc * dirB, ST + ext * dirB])
        tpost = np.array([0.0, 0.0])
    else:
        pre = np.array([[-ext, 0.0]])
        tpre = np.array([0.0])
        post = np.array([ST + ext * dirB])
        tpost = np.array([0.0])
    center = np.vstack([pre, curva, post])
    tt = np.concatenate([tpre, tcur, tpost])
    g.update(center=center, t=tt, curva=curva, ext=ext, dirB=dirB, s1=s1, s2=s2)
    return g


def tepi_jalan(center, t, Bn, db):
    """Tepi kiri (sisi dalam, + pelebaran) dan tepi kanan jalan."""
    seg = np.diff(center, axis=0)
    seg = seg / np.maximum(np.linalg.norm(seg, axis=1)[:, None], 1e-12)
    nrm = np.column_stack([-seg[:, 1], seg[:, 0]])
    vn = np.zeros_like(center)
    vn[0], vn[-1] = nrm[0], nrm[-1]
    vn[1:-1] = nrm[:-1] + nrm[1:]
    vn /= np.maximum(np.linalg.norm(vn, axis=1)[:, None], 1e-12)
    kiri = center + vn * (Bn / 2 + db * t)[:, None]
    kanan = center - vn * (Bn / 2)
    return kiri, kanan


# =============================================================================
#  GAMBAR DXF
# =============================================================================
SHEET_W, SHEET_H = 420.0, 297.0  # A3 landscape (mm)
SKALA_LIST = [50, 100, 150, 200, 250, 300, 350, 400, 500, 600, 750, 800, 1000, 1200, 1500, 2000, 2500, 3000, 5000, 7500, 10000]


class Kertas:
    """Pembantu menggambar dalam satuan lembar (mm). Titik model (m) -> lembar via S()."""

    def __init__(self, msp, ox, k, bc, pusat):
        self.m, self.ox, self.k, self.bc, self.pusat = msp, ox, k, bc, pusat

    # -- transformasi
    def S(self, p):
        return (self.pusat[0] + self.k * (p[0] - self.bc[0]), self.pusat[1] + self.k * (p[1] - self.bc[1]))

    # -- primitif
    def garis(self, a, b, layer, **kw):
        at = {"layer": layer}
        at.update(kw)
        self.m.add_line((a[0], a[1]), (b[0], b[1]), dxfattribs=at)

    def poli(self, pts, layer, close=False, **kw):
        at = {"layer": layer}
        at.update(kw)
        self.m.add_lwpolyline([(float(x), float(y)) for x, y in pts], format="xy", close=close, dxfattribs=at)

    def teks(self, s, p, h=2.5, layer="TEKS", rot=0.0, align="MIDDLE_CENTER"):
        rot = (rot + 180) % 360 - 180
        if rot > 90:
            rot -= 180
        elif rot <= -90:
            rot += 180
        t = self.m.add_text(s, height=h, dxfattribs={"layer": layer, "style": "ARIAL", "rotation": rot})
        t.set_placement((p[0], p[1]), align=_align(align))

    def tick(self, p, ang_deg, layer="DIMENSI", L=2.2):
        a = (ang_deg + 45) * D2R
        dx, dy = L * math.cos(a), L * math.sin(a)
        self.garis((p[0] - dx, p[1] - dy), (p[0] + dx, p[1] + dy), layer, lineweight=35)

    # -- dimensi garis (manual, gaya AutoCAD)
    def dim(self, p1, p2, off, teks, h=2.5):
        a, b = np.array(self.S(p1)), np.array(self.S(p2))
        d = b - a
        L = np.linalg.norm(d)
        if L < 1e-6:
            return
        d /= L
        n = np.array([-d[1], d[0]])
        a2, b2 = a + n * off, b + n * off
        sgn = 1 if off >= 0 else -1
        self.garis(a, a2 + n * 1.5 * sgn, "DIMENSI")
        self.garis(b, b2 + n * 1.5 * sgn, "DIMENSI")
        self.garis(a2, b2, "DIMENSI")
        ang = math.degrees(math.atan2(d[1], d[0]))
        self.tick(a2, ang)
        self.tick(b2, ang)
        mid = (a2 + b2) / 2 + n * 2.2 * sgn
        self.teks(teks, mid, h, "DIMENSI", ang)

    def busur_sudut(self, pusat_model, a0, a1, r_mm, teks, h=2.5, jarak=4.0):
        c = self.S(pusat_model)
        self.m.add_arc(c, r_mm, a0 % 360, a1 % 360, dxfattribs={"layer": "DIMENSI"})
        am = (a0 + a1) / 2 * D2R
        self.teks(teks, (c[0] + (r_mm + jarak) * math.cos(am), c[1] + (r_mm + jarak) * math.sin(am)), h, "DIMENSI")
        for ang in (a0, a1):
            self.tick((c[0] + r_mm * math.cos(ang * D2R), c[1] + r_mm * math.sin(ang * D2R)), ang + 90)

    def titik(self, nama, p_model, dx=3.0, dy=3.0, align="BOTTOM_LEFT"):
        c = self.S(p_model)
        self.m.add_circle(c, 0.9, dxfattribs={"layer": "TITIK"})
        self.teks(nama, (c[0] + dx, c[1] + dy), 3.0, "TEKS", align=align)


def _buat_doc():
    doc = ezdxf.new("R2010", setup=True)
    try:
        doc.units = ezdxf.units.MM
    except Exception:
        pass
    doc.header["$LTSCALE"] = 10
    if "ARIAL" not in doc.styles:
        doc.styles.add("ARIAL", font="arial.ttf")
    spesifikasi = {
        "FRAME": (7, "Continuous"), "TABEL": (7, "Continuous"), "TEKS": (7, "Continuous"),
        "TANGEN": (7, "Continuous"), "LENGKUNG": (1, "Continuous"), "TEPI": (8, "Continuous"),
        "RADIUS": (6, "DASHED"), "DIMENSI": (30, "Continuous"), "TITIK": (7, "Continuous"),
        "SUMBU": (8, "CENTER"),
    }
    for nama, (warna, lt) in spesifikasi.items():
        doc.layers.add(nama, color=warna, linetype=lt)
    return doc


def _kotak(ks, x0, y0, x1, y1, layer="FRAME", **kw):
    ks.poli([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, close=True, **kw)


def _kop_gambar(ks, ox, K, judul, nomor, skala):
    """Kop gambar di bagian bawah lembar (mengikuti contoh laporan)."""
    x0, x1 = ox + 10, ox + SHEET_W - 10
    xa, xb = x0 + 215, x0 + 335
    _kotak(ks, x0, 10, x1, 55, lineweight=50)
    for y in (20, 30, 40):
        ks.garis((x0, y), (x1, y), "FRAME")
    ks.garis((xa, 10), (xa, 40), "FRAME")
    ks.garis((xb, 10), (xb, 40), "FRAME")
    ks.garis((xb, 25), (x1, 25), "FRAME")
    ks.teks(K["proyek"].upper(), ((x0 + x1) / 2, 49.5), 3.6)
    ks.teks(str(K["tahun"]), ((x0 + x1) / 2, 43.5), 2.8)
    kiri = [("NAMA TIM", K["tim"]), ("JUDUL GAMBAR", judul), ("TANGGAL", K["tanggal"])]
    tengah = [("TIPE JALAN", K["tipe_jalan"]), ("KELAS JALAN", K["kelas"]), ("SKALA", f"1 : {skala}")]
    for i, ((l1, v1), (l2, v2)) in enumerate(zip(kiri, tengah)):
        yy = 35 - 10 * i
        ks.teks(f"{l1} = {v1}".upper(), (x0 + 3, yy), 3.0, align="MIDDLE_LEFT")
        ks.teks(f"{l2} = {v2}".upper(), (xa + 3, yy), 3.0, align="MIDDLE_LEFT")
    ks.teks("NOMOR GAMBAR", ((xb + x1) / 2, 35), 3.0)
    ks.teks(str(nomor), ((xb + x1) / 2, 17.5), 5.0)


def _tabel(ks, x, y_top, judul, data, w=(46, 38, 16), rh=6.0):
    """Tabel kecil data. data = [(label, nilai_str, satuan)]."""
    tw = sum(w)
    n = len(data) + 1
    _kotak(ks, x, y_top - n * rh, x + tw, y_top, "TABEL", lineweight=35)
    ks.teks(judul, (x + tw / 2, y_top - rh / 2), 3.0, align="MIDDLE_CENTER")
    for i, (lab, val, sat) in enumerate(data, start=1):
        yy = y_top - i * rh
        ks.garis((x, yy), (x + tw, yy), "TABEL")
        ks.teks(lab, (x + 2, yy - rh / 2), 2.4, align="MIDDLE_LEFT")
        ks.teks(val, (x + w[0] + w[1] - 2, yy - rh / 2), 2.4, align="MIDDLE_RIGHT")
        ks.teks(sat, (x + w[0] + w[1] + 2, yy - rh / 2), 2.4, align="MIDDLE_LEFT")
    ks.garis((x + w[0], y_top - rh), (x + w[0], y_top - n * rh), "TABEL")
    ks.garis((x + w[0] + w[1], y_top - rh), (x + w[0] + w[1], y_top - n * rh), "TABEL")
    return y_top - n * rh


def _detail_fc(msp, ox, g, v, y_atas):
    """Kotak detail diperbesar untuk FC (sudut belok kecil -> lengkung terlalu pipih pada gambar utama)."""
    x0, x1, y0, y1 = ox + 300, ox + 400, 68.0, y_atas
    if y1 - y0 < 45:
        return
    Tc, d, R = v["Tc"], v["delta"], v["R"]
    PI, CT, dB = g["PI"], g["ST"], g["dirB"]
    e = 0.5 * Tc
    ujung = CT + e * dB
    xmin, xmax = -e, max(PI[0], ujung[0])
    ymin, ymax = 0.0, max(ujung[1], 0.0)
    bw, bh = xmax - xmin, ymax - ymin
    N2 = next((n for n in SKALA_LIST if bw * 1000 / n <= 80 and bh * 1000 / n <= (y1 - y0) - 45), SKALA_LIST[-1])
    k2 = 1000.0 / N2
    bc = ((xmin + xmax) / 2, (ymin + ymax) / 2)
    ks = Kertas(msp, ox, k2, bc, ((x0 + x1) / 2, y0 + 10 + (y1 - y0 - 10) / 2 - 4))
    S = ks.S
    _kotak(ks, x0, y0, x1, y1, "TABEL", lineweight=35)
    ks.garis((x0, y1 - 8), (x1, y1 - 8), "TABEL")
    ks.teks(f"DETAIL TC - PI - CT   SKALA 1 : {N2}", ((x0 + x1) / 2, y1 - 4), 2.8)
    ks.garis(S((-e, 0)), S(PI), "TANGEN", lineweight=35)
    ks.garis(S(PI), S(ujung), "TANGEN", lineweight=35)
    msp.add_arc(S(g["O"]), k2 * R, 270 % 360, (270 + d) % 360, dxfattribs={"layer": "LENGKUNG", "lineweight": 70})
    ks.titik("TC", g["TC"], -6.0, -4.0)
    ks.titik("PI", PI, 2.5, -5.0)
    ks.titik("CT", CT, 2.5, 2.5)
    ks.dim(g["TC"], PI, -9, f"Tc = {v['Tc']:.4f}")
    ks.dim(PI, CT, -9, f"Tc = {v['Tc']:.4f}")
    c = S((Tc * 0.5, 0))
    ks.teks(f"Lc = {v['Lc']:.4f}   Ec = {v['Ec']:.4f}", (c[0] + 18, c[1] + 12), 2.5, "DIMENSI")
    ks.teks(f"Δ = {d:g}°", (c[0] + 18, c[1] + 17), 2.5, "DIMENSI")
    ks.teks(f"Garis radius ke pusat O  (R = {R:.4f})", (c[0] + 18, c[1] + 22), 2.5, "DIMENSI")
    ks.garis(S(g["TC"]), (S(g["TC"])[0], S(g["TC"])[1] + 8), "RADIUS")
    ks.garis(S(CT), (S(CT)[0] - 8 * math.sin(d * D2R), S(CT)[1] + 8 * math.cos(d * D2R)), "RADIUS")


def gambar_tikungan(doc, hasil, P, peleb, K, ox, nomor):
    """Gambar satu lembar tikungan pada model space dengan offset x = ox."""
    msp = doc.modelspace()
    tipe, v = hasil["tipe"], hasil["v"]
    R, d = v["R"], v["delta"]
    Ts = v["Tc"] if tipe == "FC" else v["Ts"]
    ext = max(0.25 * Ts, 0.10 * R, 22.0)
    g = bangun_geometri(hasil, ext)

    # ---- bounding box & skala
    pts = np.vstack([g["center"], g["O"], g["PI"]])
    kiri, kanan = tepi_jalan(g["center"], g["t"], P["Bn"], peleb["db"])
    pts = np.vstack([pts, kiri, kanan])
    mn, mx = pts.min(axis=0), pts.max(axis=0)
    bw, bh = mx[0] - mn[0], mx[1] - mn[1]
    GX0, GX1, GY0, GY1 = ox + 20, ox + 292, 65, 282
    mar = 24
    uw, uh = (GX1 - GX0) - 2 * mar, (GY1 - GY0) - 2 * mar
    N = next((s for s in SKALA_LIST if bw * 1000 / s <= uw and bh * 1000 / s <= uh), SKALA_LIST[-1])
    k = 1000.0 / N
    bc = ((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2)
    pusat = ((GX0 + GX1) / 2, (GY0 + GY1) / 2)
    ks = Kertas(msp, ox, k, bc, pusat)

    # ---- bingkai lembar
    _kotak(ks, ox + 0, 0, ox + SHEET_W, SHEET_H, "FRAME")
    _kotak(ks, ox + 10, 10, ox + SHEET_W - 10, SHEET_H - 10, "FRAME", lineweight=70)
    judul = f"TIKUNGAN {nomor_tikungan_label(tipe)}"
    _kop_gambar(ks, ox, K, judul, nomor, N)

    # ---- tepi jalan
    S = ks.S
    ks.poli([S(p) for p in kiri], "TEPI")
    ks.poli([S(p) for p in kanan], "TEPI")

    # ---- tangen (garis lurus) & sumbu
    TS = np.array([0.0, 0.0])
    ks.garis(S((-ext, 0)), S(g["PI"]), "TANGEN", lineweight=35)
    ks.garis(S(g["PI"]), S(g["ST"] + ext * g["dirB"]), "TANGEN", lineweight=35)

    # ---- lengkung (merah, tebal)
    if tipe == "FC":
        a0, a1 = g["arc_ang"]
        msp.add_arc(S(g["O"]), k * R, a0 % 360, a1 % 360, dxfattribs={"layer": "LENGKUNG", "lineweight": 70})
    else:
        ks.poli([S(p) for p in g["s1"]], "LENGKUNG", lineweight=70)
        ks.poli([S(p) for p in g["s2"]], "LENGKUNG", lineweight=70)
        if g["arc_ang"]:
            a0, a1 = g["arc_ang"]
            msp.add_arc(S(g["O"]), k * R, a0 % 360, a1 % 360, dxfattribs={"layer": "LENGKUNG", "lineweight": 70})

    # ---- jari-jari & garis bantu
    O = g["O"]
    if tipe == "FC":
        ujung = [g["TC"], g["CT"]]
    else:
        ujung = [g["SC"], g["CS"]]
        foot1 = np.array([v["K"], 0.0])
        ks.garis(S(O), S(foot1), "RADIUS")
        u = (g["O"] - g["PI"]) / np.linalg.norm(g["O"] - g["PI"])
        foot2 = _refleksi(foot1, g["PI"], u)
        ks.garis(S(O), S(foot2), "RADIUS")
    for p in ujung:
        ks.garis(S(O), S(p), "RADIUS")
    ks.garis(S(g["PI"]), S(O), "SUMBU")

    # ---- titik & label
    ks.titik("PI", g["PI"], 2.5, 2.5)
    ks.titik("O", O, 2.5, 2.5)
    if tipe == "FC":
        ks.titik("TC", g["TC"], -6.5, -3.5, "BOTTOM_LEFT")
        ks.titik("CT", g["CT"], 2.5, 2.5)
    else:
        ks.titik("TS", TS, -7.0, -3.5)
        ks.titik("ST", g["ST"], 2.5, 2.5)
        if v["thc"] > 1e-6:
            ks.titik("SC", g["SC"], 2.5, -5.5)
            ks.titik("CS", g["CS"], 2.5, 2.5)
        else:
            ks.titik("SS", g["SC"], 2.5, -5.5)

    # ---- dimensi
    fv = lambda x: f"{x:.4f}"
    if tipe == "FC":
        ks.dim(g["TC"], g["PI"], -9, f"Tc = {fv(v['Tc'])}")
        rm = (np.array(S(O)) + np.array(S(g["CT"]))) / 2
        ks.teks(f"R = {fv(R)}", (rm[0] + 8, rm[1]), 3.0, "DIMENSI")
        mid = O + R * np.array([math.cos((270 + d / 2) * D2R), math.sin((270 + d / 2) * D2R)])
        ks.garis(S(g["PI"]), S(mid), "DIMENSI")
        pm = (np.array(S(g["PI"])) + np.array(S(mid))) / 2
        ks.teks(f"Ec = {fv(v['Ec'])}", (pm[0] + 12, pm[1] - 3), 2.5, "DIMENSI")
        cm = np.array(S(O)) + k * R * np.array([math.cos((270 + d / 2) * D2R), math.sin((270 + d / 2) * D2R)])
        ks.teks(f"Lc = {fv(v['Lc'])}", (cm[0] + 14, cm[1] - 7), 2.5, "DIMENSI")
        r_ang = max(6.0, min(0.3 * k * R, 14))
        ks.busur_sudut(O, 270, 270 + d, r_ang, f"Δ = {d:g}°", 2.5, 4)
    else:
        ks.dim(TS, np.array([v["K"], 0.0]), -9, f"K = {fv(v['K'])}")
        ks.dim(TS, np.array([v["Xc"], 0.0]), -18, f"{'Xc' if v['thc'] > 1e-6 else 'Xs'} = {fv(v['Xc'])}")
        ks.dim(TS, g["PI"], -27, f"Ts = {fv(v['Ts'])}")
        ks.dim(TS, g["SC"], 9, f"Ls = {fv(v['Ls'])}")
        r_ang = max(8.0, min(0.30 * k * R, 22))
        th_s, th_c = v["ths"], v["thc"]
        ks.busur_sudut(O, 270, 270 + th_s, r_ang, f"θs = {th_s:.2f}°", 2.5, 4)
        if th_c > 1e-6:
            ks.busur_sudut(O, 270 + th_s, 270 + th_s + th_c, r_ang + 9, f"θc = {th_c:.2f}°", 2.5, 4)
            ks.busur_sudut(O, 270 + th_s + th_c, 270 + d, r_ang, f"θs = {th_s:.2f}°", 2.5, 4)
        else:
            ks.busur_sudut(O, 270 + th_s, 270 + d, r_ang, f"θs = {th_s:.2f}°", 2.5, 4)
        # Es: PI -> titik tengah busur
        am = (270 + d / 2) * D2R
        mid = O + R * np.array([math.cos(am), math.sin(am)])
        ks.garis(S(g["PI"]), S(mid), "DIMENSI")
        pm = (np.array(S(g["PI"])) + np.array(S(mid))) / 2
        ks.teks(f"Es = {fv(v['Es'])}", (pm[0] + 12, pm[1] - 3), 2.5, "DIMENSI")
        rm = (np.array(S(O)) + np.array(S((v["K"], 0.0)))) / 2
        ks.teks(f"R = {fv(R)}", (rm[0] - 11, rm[1]), 2.5, "DIMENSI", rot=90)
    # sudut belok Δ pada PI
    rp = 11.0
    ks.busur_sudut(g["PI"], 0, d, rp, f"Δ = {d:g}°", 2.5, 4)

    # ---- tabel data (kanan atas)
    if tipe == "FC":
        data = [
            ("Kecepatan rencana Vr", f"{P['Vr']:g}", "km/jam"), ("Radius R", f"{R:.2f}", "m"),
            ("Sudut belok Δ", f"{d:.2f}", "°"), ("Lc", f"{v['Lc']:.4f}", "m"),
            ("Tc", f"{v['Tc']:.4f}", "m"), ("Ec", f"{v['Ec']:.4f}", "m"),
        ]
    else:
        data = [
            ("Kecepatan rencana Vr", f"{P['Vr']:g}", "km/jam"), ("Radius R", f"{R:.2f}", "m"),
            ("Sudut belok Δ", f"{d:.2f}", "°"), ("Ls", f"{v['Ls']:.4f}", "m"),
            ("θs", f"{v['ths']:.4f}", "°"), ("θc", f"{v['thc']:.4f}", "°"),
            ("Lc", f"{v['Lc']:.4f}", "m"), ("Xc / Xs", f"{v['Xc']:.4f}", "m"),
            ("Yc / Ys", f"{v['Yc']:.4f}", "m"), ("P", f"{v['P']:.4f}", "m"),
            ("K", f"{v['K']:.4f}", "m"), ("Es", f"{v['Es']:.4f}", "m"),
            ("Ts", f"{v['Ts']:.4f}", "m"), ("L total", f"{v['Ltot']:.4f}", "m"),
        ]
    y_bawah = _tabel(ks, ox + 300, 280, f"DATA TIKUNGAN {tipe}", data)
    data2 = [
        ("Lebar normal Bn", f"{P['Bn']:.2f}", "m"), ("Lebar di tikungan Bt", f"{peleb['Bt']:.4f}", "m"),
        ("Pelebaran Δb", f"{peleb['db']:.4f}", "m"), ("Per sisi Δb/2", f"{peleb['db'] / 2:.4f}", "m"),
    ]
    y_bawah = _tabel(ks, ox + 300, y_bawah - 6, "PELEBARAN PERKERASAN", data2)
    data3 = [(n_, fmt_sta(s_), "") for n_, s_ in hasil["sta"]]
    y_end = _tabel(ks, ox + 300, y_bawah - 6, "STASIONING", data3, w=(46, 38, 16))
    if tipe == "FC":
        _detail_fc(msp, ox, g, v, y_end - 6)



def nomor_tikungan_label(tipe):
    return {"FC": "FC (FULL CIRCLE)", "SCS": "S-C-S (SPIRAL-CIRCLE-SPIRAL)", "SS": "S-S (SPIRAL-SPIRAL)"}[tipe]


def buat_dxf(daftar_hasil, P, peleb, K):
    """daftar_hasil: list hasil tikungan yang akan digambar (satu lembar per item)."""
    doc = _buat_doc()
    for i, h in enumerate(daftar_hasil):
        gambar_tikungan(doc, h, P, peleb, K, ox=i * (SHEET_W + 40), nomor=K["nomor"] + i)
    try:
        from ezdxf import zoom
        zoom.extents(doc.modelspace(), factor=1.05)
    except Exception:
        pass
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode("utf-8"), doc


# =============================================================================
#  EXCEL
# =============================================================================
def df_hasil(rows, teks=False):
    """teks=True -> kolom Nilai jadi string (aman untuk st.dataframe karena campuran angka & 'OK')."""
    df = pd.DataFrame(rows)
    if teks:
        df["Nilai"] = df["Nilai"].apply(lambda x: f"{x:.4f}" if isinstance(x, (int, float, np.floating)) else str(x))
    else:
        df["Nilai"] = df["Nilai"].apply(lambda x: round(x, 4) if isinstance(x, (int, float, np.floating)) else x)
    return df


def buat_excel(P, dasar, hasil, terpilih, peleb, jph, jpm, jph_tbl, sta_pi):
    buf = io.BytesIO()
    from openpyxl.styles import Alignment, Font, PatternFill

    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        # --- Sheet Parameter
        inp = pd.DataFrame(
            [
                ("Kecepatan rencana", "Vr", P["Vr"], "km/jam"),
                ("Radius tikungan rencana", "Rc", P["Rc"], "m"),
                ("Sudut belok", "Δ", P["delta"], "°"),
                ("Superelevasi maksimum", "emax", P["emax"], "-"),
                ("Superelevasi normal", "en", P["en"], "-"),
                ("STA PI", "STA PI", sta_pi, "m"),
                ("Jenis tikungan dipakai", "-", terpilih, "-"),
            ],
            columns=["Parameter", "Simbol", "Nilai", "Satuan"],
        )
        inp.to_excel(xw, sheet_name="Parameter", index=False, startrow=1)
        r0 = len(inp) + 4
        sheet = xw.sheets["Parameter"]
        sheet.cell(row=1, column=1, value="DATA INPUT")
        cur = r0
        for tp in ("FC", "SCS", "SS"):
            h = hasil[tp]
            sheet.cell(row=cur, column=1, value=f"HASIL PERHITUNGAN TIKUNGAN {tp}" + ("  (DIPAKAI)" if tp == terpilih else ""))
            df_hasil(h["rows"]).to_excel(xw, sheet_name="Parameter", index=False, startrow=cur)
            cur += len(h["rows"]) + 3
            sta = pd.DataFrame([(n, round(s, 3), fmt_sta(s)) for n, s in h["sta"]], columns=["Titik", "STA (m)", "STA"])
            sta.to_excel(xw, sheet_name="Parameter", index=False, startrow=cur)
            cur += len(sta) + 3
        # --- Sheet Pelebaran
        pel_in = pd.DataFrame(
            [("p", P["p"], "m"), ("A", P["A"], "m"), ("b", P["b"], "m"), ("n", P["n"], "lajur"), ("Bn", P["Bn"], "m"), ("R", P["Rc"], "m")],
            columns=["Parameter", "Nilai", "Satuan"],
        )
        pel_in.to_excel(xw, sheet_name="Pelebaran", index=False, startrow=1)
        xw.sheets["Pelebaran"].cell(row=1, column=1, value="DATA KENDARAAN RENCANA & JALAN")
        sr = len(pel_in) + 4
        xw.sheets["Pelebaran"].cell(row=sr, column=1, value="HASIL PELEBARAN")
        df_hasil(peleb["rows"]).to_excel(xw, sheet_name="Pelebaran", index=False, startrow=sr)
        # --- Sheet Jarak Pandang
        rows_jph = [
            baris("Jarak reaksi", "d₁", "Vr·t / 3,6", jph[1], "m"),
            baris("Jarak pengereman", "d₂", "Vr² / [2·3,6²·9,81·(a/9,81 ± G)]", jph[2], "m"),
            baris("Jarak pandang henti", "JPH", "d₁ + d₂", jph[0], "m"),
            baris("JPH minimum standar", "JPH std", "tabel Bina Marga", jph_tbl, "m"),
        ]
        rows_jpm = [
            baris("Waktu penyesuaian awal", "T₁", "2,12 + 0,026·Vr", jpm["T1"], "s"),
            baris("Waktu di lajur lawan", "T₂", "6,56 + 0,048·Vr", jpm["T2"], "s"),
            baris("Percepatan rata-rata", "a", "2,052 + 0,0036·Vr", jpm["a"], "km/jam/s"),
            baris("Jarak selama waktu tanggap", "d₁", "0,278·T₁·(Vr − m + a·T₁/2)", jpm["d1"], "m"),
            baris("Jarak selama mendahului", "d₂", "0,278·Vr·T₂", jpm["d2"], "m"),
            baris("Jarak bebas", "d₃", "30 – 100 m", jpm["d3"], "m"),
            baris("Jarak kendaraan lawan", "d₄", "2/3·d₂", jpm["d4"], "m"),
            baris("Jarak pandang mendahului", "JPM", "d₁ + d₂ + d₃ + d₄", jpm["JPM"], "m"),
            baris("JPM minimum standar", "JPM std", "TPGJAK 038/TBM/1997", _nearest(JPM_STD, P["Vr"]), "m"),
        ]
        df_hasil(rows_jph).to_excel(xw, sheet_name="Jarak Pandang", index=False, startrow=1)
        ws = xw.sheets["Jarak Pandang"]
        ws.cell(row=1, column=1, value="JARAK PANDANG HENTI (JPH)")
        s2 = len(rows_jph) + 4
        ws.cell(row=s2, column=1, value="JARAK PANDANG MENDAHULUI (JPM)")
        df_hasil(rows_jpm).to_excel(xw, sheet_name="Jarak Pandang", index=False, startrow=s2)

        # --- format
        hdr_fill = PatternFill("solid", fgColor="1F4E78")
        for ws in xw.book.worksheets:
            ws.sheet_view.showGridLines = False
            for row in ws.iter_rows():
                for c in row:
                    if c.value is not None and c.column == 1 and isinstance(c.value, str) and c.value.isupper():
                        c.font = Font(bold=True, size=12, color="1F4E78")
                    if c.value in ("Parameter", "Titik") and c.column == 1:
                        for cc in row:
                            if cc.value is not None:
                                cc.font = Font(bold=True, color="FFFFFF")
                                cc.fill = hdr_fill
                                cc.alignment = Alignment(horizontal="center")
            for col in ws.columns:
                w = max((len(str(c.value)) for c in col if c.value is not None), default=8)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, w + 2), 48)
    return buf.getvalue()


# =============================================================================
#  PRATINJAU DXF (render ezdxf -> PNG)
# =============================================================================
def pratinjau_png(doc):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    fig = plt.figure(figsize=(16, 11.5))
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    Frontend(ctx, MatplotlibBackend(ax)).draw_layout(doc.modelspace(), finalize=True)
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=130)
    plt.close(fig)
    return out.getvalue()


# ===== UI =====================================================================
def main():
    st.set_page_config(page_title="Kalkulator Geometri Tikungan", page_icon="🛣️", layout="wide")
    st.title("🛣️ Kalkulator Geometri Tikungan Jalan")
    st.caption("Perhitungan FC • SCS • SS, pelebaran perkerasan, jarak pandang, output Excel & CAD (.dxf)")

    # ------------------------------------------------------------- SIDEBAR
    with st.sidebar:
        st.header("⚙️ Input Parameter")
        Vr = st.number_input("Kecepatan rencana, Vr (km/jam)", 20.0, 120.0, 80.0, 5.0)
        Rc = st.number_input("Radius tikungan rencana, Rc (m)", 10.0, 5000.0, 240.0, 1.0)
        delta = st.number_input("Sudut belok, Δ (°)", 0.1, 179.0, 16.8, 0.1, format="%.2f")
        emax = st.number_input("Superelevasi maksimum, e max (%)", 4.0, 10.0, 8.0, 0.5) / 100
        sta_pi = st.number_input("STA PI (m)", 0.0, 1_000_000.0, 385.0, 5.0)
        pilih = st.selectbox("Jenis tikungan yang digambar", ["Otomatis (rekomendasi)", "FC", "SCS", "SS"])
        semua = st.checkbox("Gambar ketiganya (FC, SCS, SS) dalam satu DXF", value=False)

        with st.expander("Parameter lengkung peralihan"):
            en = st.number_input("e normal (%)", 0.0, 6.0, 2.0, 0.5) / 100
            Cc = st.number_input("C (perubahan percepatan, m/det³)", 0.1, 2.0, 0.4, 0.1)
            C1 = st.number_input("C kriteria 1 (Shortt)", 0.1, 5.0, 1.0, 0.1,
                                 help="Laporan memakai angka yang setara C = 1.")
            T = st.number_input("T waktu tempuh (detik)", 1.0, 6.0, 3.0, 0.5)
            re = st.number_input("re landai relatif (0 = otomatis)", 0.0, 0.1, 0.0, 0.005, format="%.3f")
            Ls_rencana = st.number_input("Ls rencana SCS (m, 0 = otomatis)", 0.0, 500.0, 0.0, 5.0)

        with st.expander("Parameter pelebaran perkerasan"):
            p_ = st.number_input("p – jarak gandar (m)", 0.1, 20.0, 7.6, 0.1)
            A_ = st.number_input("A – tonjolan depan (m)", 0.0, 10.0, 2.1, 0.1)
            b_ = st.number_input("b – lebar kendaraan (m)", 1.0, 4.0, 2.6, 0.1)
            n_ = st.number_input("n – jumlah lajur", 1, 6, 2, 1)
            Bn_ = st.number_input("Bn – lebar perkerasan normal (m)", 3.0, 30.0, 7.0, 0.1)
            kz_ = st.number_input("Koefisien Z", 0.05, 0.2, 0.100, 0.005, format="%.3f",
                                  help="Laporan memakai 0,1. Rumus buku Bina Marga: 0,105.")
            tdn = st.checkbox("Pakai (n+1)·Td seperti laporan", value=True,
                              help="Jika tidak dicentang dipakai (n−1)·Td.")

        with st.expander("Parameter jarak pandang"):
            t_r = st.number_input("t – waktu reaksi (detik)", 1.0, 4.0, 2.5, 0.1)
            a_dec = st.number_input("a – perlambatan (m/det²)", 1.0, 6.0, 3.4, 0.1)
            G = st.number_input("G – kelandaian (%) (+ tanjakan, − turunan)", -15.0, 15.0, 0.0, 0.5) / 100
            m_sel = st.number_input("m – selisih kecepatan (km/jam)", 5.0, 20.0, 15.0, 1.0)
            d3 = st.number_input("d₃ – jarak bebas (m)", 30.0, 100.0, 100.0, 5.0)

        with st.expander("Kop gambar CAD"):
            K = {
                "proyek": st.text_input("Judul proyek", "Perencanaan Geometrik Jalan"),
                "tahun": st.text_input("Tahun", str(date.today().year)),
                "tim": st.text_input("Nama tim", "Tim Perencana"),
                "tipe_jalan": st.text_input("Tipe jalan", "Arteri Primer"),
                "kelas": st.text_input("Kelas jalan", "Kelas 1"),
                "tanggal": st.text_input("Tanggal", date.today().strftime("%d %B %Y")),
                "nomor": int(st.number_input("Nomor gambar awal", 1, 999, 1, 1)),
            }

    P = dict(Vr=Vr, Rc=Rc, delta=delta, emax=emax, en=en, Cc=Cc, C1=C1, T=T, re=re,
             Ls_rencana=Ls_rencana, p=p_, A=A_, b=b_, n=int(n_), Bn=Bn_, kz=kz_, td_n_plus_1=tdn)

    # ------------------------------------------------------------- HITUNG
    dasar = hitung_dasar(P)
    hasil = {"FC": hitung_fc(P, sta_pi), "SCS": hitung_scs(P, sta_pi), "SS": hitung_ss(P, sta_pi)}
    saran = rekomendasi(P, hasil)
    terpilih = saran if pilih.startswith("Otomatis") else pilih
    peleb = hitung_pelebaran(P, Rc, Vr)
    jph = hitung_jph(Vr, t_r, a_dec, G)
    jpm = hitung_jpm(Vr, m_sel, d3)

    # ------------------------------------------------------------- RINGKASAN
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("f (koef. gesek)", f"{dasar['f']:.3f}")
    c2.metric("Rmin", f"{dasar['Rmin']:.2f} m", "Rc memenuhi ✔" if dasar["R_ok"] else "Rc < Rmin ✘",
              delta_color="normal" if dasar["R_ok"] else "inverse")
    c3.metric("Rekomendasi tikungan", saran)
    c4.metric("Tikungan yang dipakai", terpilih)

    tab1, tab2, tab3, tab4 = st.tabs(["📐 Parameter Utama", "↔️ Pelebaran Perkerasan", "👁️ Jarak Pandang", "🖼️ Pratinjau Gambar"])

    # ---- TAB 1
    with tab1:
        st.subheader("Perhitungan per jenis tikungan")
        nama_lengkap = {"FC": "Full Circle (FC)", "SCS": "Spiral-Circle-Spiral (SCS)", "SS": "Spiral-Spiral (SS)"}
        for tp in ("FC", "SCS", "SS"):
            h = hasil[tp]
            ikon = "✅" if h["ok"] else "⚠️"
            tag = " — DIPAKAI" if tp == terpilih else ""
            with st.expander(f"{ikon} {nama_lengkap[tp]}{tag}", expanded=(tp == terpilih)):
                for ps in h["pesan"]:
                    st.warning(ps)
                if not h["pesan"]:
                    st.success("Semua syarat terpenuhi.")
                df = df_hasil(h["rows"], teks=True)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.markdown("**Stasioning**")
                st.dataframe(pd.DataFrame([(n, fmt_sta(s)) for n, s in h["sta"]], columns=["Titik", "STA"]),
                             use_container_width=True, hide_index=True)

    # ---- TAB 2
    with tab2:
        st.subheader(f"Pelebaran perkerasan di tikungan (R = {Rc:g} m, Vr = {Vr:g} km/jam)")
        a, b, c = st.columns(3)
        a.metric("Lebar di tikungan, Bt", f"{peleb['Bt']:.4f} m")
        b.metric("Pelebaran total, Δb", f"{peleb['db_raw']:.4f} m")
        c.metric("Pelebaran per sisi", f"{peleb['db_raw'] / 2:.4f} m")
        if peleb["db_raw"] <= 0:
            st.info("Δb ≤ 0 → tidak diperlukan pelebaran perkerasan.")
        st.dataframe(df_hasil(peleb["rows"], teks=True), use_container_width=True, hide_index=True)

    # ---- TAB 3
    with tab3:
        st.subheader("Jarak Pandang Henti (JPH) dan Mendahului (JPM)")
        jph_std = _nearest(JPH_STD, Vr)
        jpm_std = _nearest(JPM_STD, Vr)
        a, b = st.columns(2)
        a.metric("JPH", f"{jph[0]:.2f} m", f"standar min. {jph_std} m", delta_color="off")
        b.metric("JPM", f"{jpm['JPM']:.2f} m", f"standar min. {jpm_std} m", delta_color="off")
        if jph[0] < jph_std:
            st.warning("JPH hitungan di bawah standar minimum.")
        st.markdown("**JPH**")
        st.dataframe(df_hasil(teks=True, rows=[
            baris("Jarak reaksi", "d₁", "Vr·t / 3,6", jph[1], "m"),
            baris("Jarak pengereman", "d₂", "Vr² / [2·3,6²·9,81·(a/9,81 ± G)]", jph[2], "m"),
            baris("Jarak pandang henti", "JPH", "d₁ + d₂", jph[0], "m"),
        ]), use_container_width=True, hide_index=True)
        st.markdown("**JPM**")
        st.dataframe(df_hasil(teks=True, rows=[
            baris("Waktu penyesuaian awal", "T₁", "2,12 + 0,026·Vr", jpm["T1"], "s"),
            baris("Waktu di lajur lawan", "T₂", "6,56 + 0,048·Vr", jpm["T2"], "s"),
            baris("Percepatan rata-rata", "a", "2,052 + 0,0036·Vr", jpm["a"], "km/jam/s"),
            baris("Jarak selama waktu tanggap", "d₁", "0,278·T₁·(Vr − m + a·T₁/2)", jpm["d1"], "m"),
            baris("Jarak selama mendahului", "d₂", "0,278·Vr·T₂", jpm["d2"], "m"),
            baris("Jarak bebas", "d₃", "30 – 100 m", jpm["d3"], "m"),
            baris("Jarak kendaraan lawan", "d₄", "2/3·d₂", jpm["d4"], "m"),
            baris("Jarak pandang mendahului", "JPM", "d₁ + d₂ + d₃ + d₄", jpm["JPM"], "m"),
        ]), use_container_width=True, hide_index=True)

    # ------------------------------------------------------------- DXF
    dxf_bytes, doc, err = None, None, None
    daftar = [hasil[t] for t in (("FC", "SCS", "SS") if semua else (terpilih,))]
    layak = [h for h in daftar if h["tipe"] != "SCS" or h["v"]["thc"] > 0]
    if not layak:
        err = "Tikungan terpilih tidak dapat digambar (θc ≤ 0). Pilih SS."
    else:
        dxf_bytes, doc = buat_dxf(layak, P, peleb, K)

    # ---- TAB 4
    with tab4:
        if err:
            st.error(err)
        else:
            try:
                st.image(pratinjau_png(doc), caption="Pratinjau gambar CAD (isi file .dxf yang sama)", use_container_width=True)
            except Exception as e:  # matplotlib / addon drawing tidak tersedia
                st.info(f"Pratinjau tidak tersedia ({e}). File DXF tetap bisa diunduh dan dibuka di AutoCAD.")

    # ------------------------------------------------------------- DOWNLOAD
    st.divider()
    d1, d2 = st.columns(2)
    xlsx = buat_excel(P, dasar, hasil, terpilih, peleb, jph, jpm, _nearest(JPH_STD, Vr), sta_pi)
    d1.download_button("📥 Download Excel (.xlsx)", xlsx, file_name=f"Hitungan_Tikungan_{terpilih}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    if dxf_bytes:
        d2.download_button("📥 Download CAD (.dxf)", dxf_bytes, file_name=f"Tikungan_{'ALL' if semua else terpilih}.dxf",
                           mime="application/dxf", use_container_width=True)


if __name__ == "__main__":
    main()
