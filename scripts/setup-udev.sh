#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# setup-udev.sh — gera /etc/udev/rules.d/99-ups.rules amarrando cada nobreak
# TS Shara (conversor CH340, VID 1a86 / PID 7523) à sua PORTA USB FÍSICA.
#
# Por que amarrar pela porta física: todos os cabos CH340 têm o mesmo VID/PID,
# então o Linux sorteia quem vira ttyUSB0/ttyUSB1 a cada boot. Travando por
# KERNELS (ex.: "1-1.3") o /dev/TSSHARA0 sempre aponta pro mesmo nobreak.
#
# Uso:
#   ./scripts/setup-udev.sh            # interativo, escreve as regras e recarrega
#   ./scripts/setup-udev.sh --dry-run  # só mostra o que seria gerado
# -----------------------------------------------------------------------------
set -euo pipefail

VID="1a86"
PID="7523"
RULES_FILE="/etc/udev/rules.d/99-ups.rules"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

c_reset=$'\033[0m'; c_bold=$'\033[1m'; c_green=$'\033[32m'; c_yellow=$'\033[33m'; c_red=$'\033[31m'

die() { echo "${c_red}erro:${c_reset} $*" >&2; exit 1; }

command -v udevadm >/dev/null || die "udevadm não encontrado (pacote systemd/udev)."

# Extrai a porta física (KERNELS) de um /dev/ttyUSB*: o segmento do DEVPATH no
# formato N-N(.N)* mais profundo, ex.: 1-1.3 (ignora a interface 1-1.3:1.0).
porta_fisica() {
    local dev="$1" devpath
    devpath="$(udevadm info -q property -n "$dev" | sed -n 's/^DEVPATH=//p')"
    echo "$devpath" | tr '/' '\n' | grep -E '^[0-9]+-[0-9]+(\.[0-9]+)*$' | tail -1
}

is_ch340() {
    local dev="$1" props
    props="$(udevadm info -q property -n "$dev" 2>/dev/null || true)"
    [[ "$(sed -n 's/^ID_VENDOR_ID=//p' <<<"$props")" == "$VID" ]] && \
    [[ "$(sed -n 's/^ID_MODEL_ID=//p'  <<<"$props")" == "$PID" ]]
}

# --- Descoberta -------------------------------------------------------------
echo "${c_bold}Procurando conversores CH340 (VID $VID / PID $PID)...${c_reset}"
declare -a DEVS=() PORTAS=()
shopt -s nullglob
for dev in /dev/ttyUSB*; do
    if is_ch340 "$dev"; then
        porta="$(porta_fisica "$dev")"
        [[ -z "$porta" ]] && { echo "${c_yellow}aviso:${c_reset} não achei a porta física de $dev, pulando."; continue; }
        DEVS+=("$dev"); PORTAS+=("$porta")
    fi
done
shopt -u nullglob

[[ ${#DEVS[@]} -eq 0 ]] && die "nenhum CH340 conectado. Espete os cabos dos nobreaks e rode de novo."

echo "Encontrei ${#DEVS[@]} dispositivo(s):"
for i in "${!DEVS[@]}"; do
    printf "  [%d] %s  →  porta física ${c_green}%s${c_reset}\n" "$i" "${DEVS[$i]}" "${PORTAS[$i]}"
done
echo
echo "${c_yellow}Dica:${c_reset} se não souber qual porta é qual nobreak, cancele (Ctrl+C),"
echo "desconecte/reconecte só o cabo de UM nobreak, rode 'dmesg | grep ttyUSB | tail'"
echo "e observe qual porta física apareceu."
echo

# --- Atribuição interativa --------------------------------------------------
declare -a LINHAS=()
for i in "${!DEVS[@]}"; do
    default="TSSHARA$i"
    read -rp "Nome do symlink para ${DEVS[$i]} (porta ${PORTAS[$i]}) [$default]: " nome
    nome="${nome:-$default}"
    nome="${nome#/dev/}"  # aceita se a pessoa digitar /dev/TSSHARA0
    LINHAS+=("SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"$VID\", ATTRS{idProduct}==\"$PID\", KERNELS==\"${PORTAS[$i]}\", SYMLINK+=\"$nome\"")
done

CONTEUDO=$(printf '%s\n' \
    "# Gerado por scripts/setup-udev.sh em $(date -Iseconds)" \
    "# Uma linha por nobreak, travado pela porta USB física (KERNELS)." \
    "${LINHAS[@]}")

echo
echo "${c_bold}Regras a serem gravadas em $RULES_FILE:${c_reset}"
echo "-----------------------------------------------------------------"
echo "$CONTEUDO"
echo "-----------------------------------------------------------------"

if [[ $DRY_RUN -eq 1 ]]; then
    echo "${c_yellow}--dry-run:${c_reset} nada foi escrito."
    exit 0
fi

read -rp "Gravar e recarregar as regras agora? [s/N]: " confirma
[[ "${confirma,,}" == "s" ]] || die "cancelado pelo usuário."

SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"
echo "$CONTEUDO" | $SUDO tee "$RULES_FILE" >/dev/null
$SUDO udevadm control --reload-rules
$SUDO udevadm trigger

echo "${c_green}OK.${c_reset} Symlinks criados:"
sleep 1
for l in "${LINHAS[@]}"; do
    nome="$(sed -n 's/.*SYMLINK+="\([^"]*\)".*/\1/p' <<<"$l")"
    if [[ -e "/dev/$nome" ]]; then
        printf "  /dev/%s → %s\n" "$nome" "$(readlink -f "/dev/$nome")"
    else
        echo "  ${c_yellow}/dev/$nome ainda não apareceu — verifique com: ls -l /dev/TSSHARA*${c_reset}"
    fi
done
