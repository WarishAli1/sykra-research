export const PASSWORD_MIN_LENGTH = 12;

export type PasswordRequirement = {
  label: string;
  valid: boolean;
};

export function passwordRequirements(password: string): PasswordRequirement[] {
  return [
    { label: `At least ${PASSWORD_MIN_LENGTH} characters`, valid: password.length >= PASSWORD_MIN_LENGTH },
    { label: "One uppercase letter", valid: /[A-Z]/.test(password) },
    { label: "One lowercase letter", valid: /[a-z]/.test(password) },
    { label: "One number", valid: /\d/.test(password) },
    { label: "One special character", valid: /[^A-Za-z0-9\s]/.test(password) },
  ];
}

export function passwordIsValid(password: string): boolean {
  return passwordRequirements(password).every((requirement) => requirement.valid);
}
