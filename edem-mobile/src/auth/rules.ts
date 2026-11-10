import type { User } from "../api/client";

export class NotADonorError extends Error {
  constructor() {
    super("This app is for blood donors. Hospitals and blood banks use the E-DEM website.");
    this.name = "NotADonorError";
  }
}

/** The mobile app is for donors only. Anyone else is refused before any tokens are stored. */
export function ensureDonor(user: Pick<User, "role">): void {
  if (user.role !== "donor") throw new NotADonorError();
}
