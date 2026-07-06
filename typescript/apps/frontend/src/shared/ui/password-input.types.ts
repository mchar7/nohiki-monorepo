import type { ComponentProps } from 'react';

interface PasswordInputProps extends Omit<ComponentProps<'input'>, 'type'> {}

export type { PasswordInputProps };
