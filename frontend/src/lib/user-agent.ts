/** Minimal, dependency-free UA summary for the sessions list ("Chrome · Windows"). */
export function describeUserAgent(ua: string | null | undefined): { label: string; mobile: boolean } {
  if (!ua) return { label: "Dispositivo desconhecido", mobile: false };
  const browser =
    /Edg\//.test(ua) ? "Edge"
    : /OPR\/|Opera/.test(ua) ? "Opera"
    : /Firefox\//.test(ua) ? "Firefox"
    : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari"
    : "Navegador";
  const os =
    /Windows/.test(ua) ? "Windows"
    : /iPhone|iPad|iPod/.test(ua) ? "iOS"
    : /Android/.test(ua) ? "Android"
    : /Mac OS X/.test(ua) ? "macOS"
    : /Linux/.test(ua) ? "Linux"
    : "Sistema desconhecido";
  return { label: `${browser} · ${os}`, mobile: /Mobile|iPhone|Android/.test(ua) };
}
