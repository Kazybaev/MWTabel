const PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*";

export function generateStrongPassword(length = 14) {
  const size = Math.max(10, length);
  const randomValues = new Uint32Array(size);
  globalThis.crypto.getRandomValues(randomValues);

  return Array.from(randomValues, (value) => PASSWORD_ALPHABET[value % PASSWORD_ALPHABET.length]).join("");
}
