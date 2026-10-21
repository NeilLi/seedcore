/** Structural component contract shared by source-pinned offline consumers. */
import type { ValidateFunction } from 'ajv';
import generatedValidator from './robotComponentValidator.js';
import { canonicalAssemblyString } from './robotAssemblyContracts.js';

const validate = generatedValidator as ValidateFunction;
export function assertComponentStructure(raw: unknown): void {
  canonicalAssemblyString(raw);
  if (!validate(raw)) throw new Error(`Component schema: ${validate.errors?.map(e => `${e.instancePath} ${e.message}`).join('; ')}`);
}
