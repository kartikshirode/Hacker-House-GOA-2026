// Goa flavor x builder flavor. Two pools, one pick from each.

const GOA = [
  "Kokum",
  "Palm",
  "Monsoon",
  "Susegad",
  "Feni",
  "Cashew",
  "Coconut",
  "Laterite",
  "Mandovi",
  "Anjuna",
  "Baga",
  "Tide",
  "Coral",
  "Paddy",
  "Poder",
  "Balcao",
  "Shack",
  "Spice Coast",
  "Dune",
  "Vagator",
] as const;

const BUILDER = [
  "Compiler",
  "Captain",
  "Debugger",
  "Shipwright",
  "Architect",
  "Wrangler",
  "Whisperer",
  "Navigator",
  "Alchemist",
  "Smith",
  "Pilot",
  "Stacker",
  "Refactorer",
  "Optimizer",
  "Bootstrapper",
  "Tinkerer",
  "Deployer",
  "Maintainer",
  "Prototyper",
  "Founder",
] as const;

export function generateTitle(rng: () => number = Math.random, exclude?: string): string {
  for (let i = 0; i < 20; i++) {
    const t = `${GOA[Math.floor(rng() * GOA.length)]} ${BUILDER[Math.floor(rng() * BUILDER.length)]}`;
    if (t !== exclude) return t;
  }
  return `${GOA[0]} ${BUILDER[0]}`;
}

export const TITLE_POOLS = { GOA, BUILDER };
