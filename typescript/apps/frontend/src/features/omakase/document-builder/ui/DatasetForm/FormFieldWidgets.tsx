import { Checkbox } from '@shared/ui/checkbox.tsx';
import { Input } from '@shared/ui/input.tsx';
import { Label } from '@shared/ui/label.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@shared/ui/select.tsx';
import { Textarea } from '@shared/ui/textarea.tsx';
import type { JSX } from 'react';
import type { UseFormRegisterReturn } from 'react-hook-form';
import type { AriaAttributes, CommonFormProps } from './FormFieldWidgetModel.ts';

const REQUIRED_INDICATOR = '*';

interface TextareaFieldProps {
  readonly commonProps: CommonFormProps;
  readonly hasError: boolean;
}

function TextareaField({ commonProps, hasError }: TextareaFieldProps): JSX.Element {
  return (
    <Textarea
      {...commonProps}
      className={hasError ? 'border-destructive focus:border-destructive' : ''}
      rows={4}
    />
  );
}

interface SelectFieldProps {
  readonly commonProps: CommonFormProps;
  readonly hasError: boolean;
  readonly enumValues: unknown[];
  readonly defaultValue: unknown;
  readonly placeholder: string;
  readonly ariaAttributes: AriaAttributes;
}

function SelectField({
  commonProps,
  hasError,
  enumValues,
  defaultValue,
  placeholder,
  ariaAttributes,
}: SelectFieldProps): JSX.Element {
  const handleValueChange = (value: string): void => {
    commonProps.onChange({ target: { value, name: commonProps.name } });
  };

  return (
    <Select onValueChange={handleValueChange} defaultValue={defaultValue as string}>
      <SelectTrigger
        className={hasError ? 'border-destructive focus:border-destructive' : ''}
        {...ariaAttributes}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {enumValues.map((value) => (
          <SelectItem key={String(value)} value={String(value)}>
            {String(value)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

interface CheckboxFieldProps {
  readonly registerProps: UseFormRegisterReturn;
  readonly hasError: boolean;
  readonly fieldId: string;
  readonly label: string;
  readonly required: boolean;
  readonly requiredLabel: string;
}

function CheckboxField({
  registerProps,
  hasError,
  fieldId,
  label,
  required,
  requiredLabel,
}: CheckboxFieldProps): JSX.Element {
  const handleCheckedChange = (checked: boolean): void => {
    const event = {
      target: {
        name: registerProps.name,
        value: checked,
        type: 'checkbox',
      },
    };
    registerProps.onChange(event);
  };

  return (
    <div className="flex items-center space-x-2">
      <Checkbox
        id={fieldId}
        {...registerProps}
        className={hasError ? 'border-destructive' : ''}
        onCheckedChange={handleCheckedChange}
      />
      <Label
        htmlFor={fieldId}
        className="font-medium text-sm leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
      >
        {label}
        {required ? (
          <span className="ml-1 text-destructive" title={requiredLabel}>
            {REQUIRED_INDICATOR}
          </span>
        ) : null}
      </Label>
    </div>
  );
}

interface PasswordInputFieldProps {
  readonly commonProps: CommonFormProps;
  readonly hasError: boolean;
  readonly showPassword: boolean;
  readonly showPasswordLabel: string;
  readonly hidePasswordLabel: string;
  readonly onTogglePassword: () => void;
}

function PasswordInputField({
  commonProps,
  hasError,
  showPassword,
  showPasswordLabel,
  hidePasswordLabel,
  onTogglePassword,
}: PasswordInputFieldProps): JSX.Element {
  return (
    <div className="relative">
      <Input
        {...commonProps}
        type={showPassword ? 'text' : 'password'}
        className={hasError ? 'border-destructive pr-10 focus:border-destructive' : 'pr-10'}
      />
      <button
        type="button"
        className="absolute inset-y-0 right-0 flex items-center pr-3"
        onClick={onTogglePassword}
        aria-label={showPassword ? hidePasswordLabel : showPasswordLabel}
        tabIndex={0}
      >
        {showPassword ? '\u{1F648}' : '\u{1F441}\uFE0F'}
      </button>
    </div>
  );
}

interface InputFieldProps {
  readonly commonProps: CommonFormProps;
  readonly hasError: boolean;
  readonly inputType: string;
  readonly type?: string | undefined;
}

function InputField({ commonProps, hasError, inputType, type }: InputFieldProps): JSX.Element {
  const baseProps = {
    ...commonProps,
    type: inputType,
    className: hasError ? 'border-destructive focus:border-destructive' : '',
  };

  const additionalProps: Record<string, string> = {};
  if (inputType === 'email') {
    additionalProps.autoComplete = 'email';
  } else if (inputType === 'number') {
    additionalProps.step = type === 'integer' ? '1' : 'any';
  }

  return <Input {...baseProps} {...additionalProps} />;
}

export { CheckboxField, InputField, PasswordInputField, SelectField, TextareaField };
