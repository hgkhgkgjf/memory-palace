export const formatScore = (value) => {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(3) : '-';
};
