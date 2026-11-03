// DaftWatch: BER ratings as the coloured energy-label badge.
AdWatch.formats.ber = v => {
  const band = /^[A-G]/.test(v) ? v[0] : "X";
  return `<span class="ber ber-${band}">${AdWatch.esc(v)}</span>`;
};
