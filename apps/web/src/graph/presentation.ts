export function usesLargeNodes(nodeCount: number, threshold: number): boolean {
  return threshold > 0 && nodeCount < threshold;
}

export function graphNodeSize(
  degree: number,
  nodeCount: number,
  threshold: number,
): number {
  const connectivity = Math.sqrt(Math.max(0, degree));
  if (usesLargeNodes(nodeCount, threshold))
    return Math.max(12, Math.min(22, 12 + connectivity * 2.2));
  return Math.max(3, Math.min(11, 3 + connectivity * 1.8));
}
