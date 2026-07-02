import type { JSX } from 'react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UIHints } from '../../lib/template.ts';
import type { FormErrors, FormRegisterFunction } from '../../model/index.ts';
import { CheckboxLayout, StandardFieldLayout } from './FormFieldLayout.tsx';
import type { AriaAttributes, CommonFormProps, WidgetType } from './FormFieldWidgetModel.ts';
import { getDefaultWidget, WIDGET_TYPES } from './FormFieldWidgetModel.ts';
import {
  CheckboxField,
  InputField,
  PasswordInputField,
  SelectField,
  TextareaField,
} from './FormFieldWidgets.tsx';

interface FormFieldProps {
  name: string;
  label: string;
  description?: string | undefined;
  type: 'string' | 'number' | 'integer' | 'boolean' | 'date' | 'text';
  format?: string | undefined;
  required?: boolean | undefined;
  register: FormRegisterFunction;
  errors: FormErrors;
  uiHints?: UIHints | undefined;
  enumValues?: unknown[] | undefined;
  defaultValue?: unknown;
  widget?: string | undefined;
  placeholder?: string | undefined;
}

interface FieldRendererParams {
  widget: string | WidgetType;
  commonProps: CommonFormProps;
  hasError: boolean;
  enumValues: unknown[] | undefined;
  defaultValue: unknown;
  label: string;
  ariaAttributes: AriaAttributes;
  registerProps: ReturnType<FormRegisterFunction>;
  fieldId: string;
  required: boolean;
  requiredLabel: string;
  showPassword: boolean;
  selectPlaceholder: string;
  showPasswordLabel: string;
  hidePasswordLabel: string;
  onTogglePassword: () => void;
  type: string;
}

function renderFieldByWidget({
  widget,
  commonProps,
  hasError,
  enumValues,
  defaultValue,
  label,
  ariaAttributes,
  registerProps,
  fieldId,
  required,
  requiredLabel,
  showPassword,
  selectPlaceholder,
  showPasswordLabel,
  hidePasswordLabel,
  onTogglePassword,
  type,
}: FieldRendererParams): JSX.Element {
  switch (widget) {
    case WIDGET_TYPES.TEXTAREA:
      return <TextareaField commonProps={commonProps} hasError={hasError} />;

    case WIDGET_TYPES.SELECT:
      return (
        <SelectField
          commonProps={commonProps}
          hasError={hasError}
          enumValues={enumValues ?? []}
          defaultValue={defaultValue}
          placeholder={selectPlaceholder}
          ariaAttributes={ariaAttributes}
        />
      );

    case WIDGET_TYPES.CHECKBOX:
      return (
        <CheckboxField
          registerProps={registerProps}
          hasError={hasError}
          fieldId={fieldId}
          label={label}
          required={required}
          requiredLabel={requiredLabel}
        />
      );

    case WIDGET_TYPES.PASSWORD:
      return (
        <PasswordInputField
          commonProps={commonProps}
          hasError={hasError}
          showPassword={showPassword}
          showPasswordLabel={showPasswordLabel}
          hidePasswordLabel={hidePasswordLabel}
          onTogglePassword={onTogglePassword}
        />
      );

    case WIDGET_TYPES.EMAIL:
      return <InputField commonProps={commonProps} hasError={hasError} inputType="email" />;

    case WIDGET_TYPES.DATE:
      return <InputField commonProps={commonProps} hasError={hasError} inputType="date" />;

    case WIDGET_TYPES.NUMBER:
      return (
        <InputField commonProps={commonProps} hasError={hasError} inputType="number" type={type} />
      );

    default:
      return <InputField commonProps={commonProps} hasError={hasError} inputType="text" />;
  }
}

interface BuildAriaParams {
  fieldId: string;
  descriptionId: string;
  errorId: string;
  description: string | undefined;
  hasError: boolean;
  required: boolean;
}

function buildAriaAttributes({
  fieldId,
  descriptionId,
  errorId,
  description,
  hasError,
  required,
}: BuildAriaParams): AriaAttributes {
  return {
    'aria-labelledby': fieldId,
    'aria-describedby': description ? descriptionId : undefined,
    'aria-invalid': hasError,
    'aria-errormessage': hasError ? errorId : undefined,
    'aria-required': required,
  };
}

export function FormField(props: Readonly<FormFieldProps>): JSX.Element {
  const {
    name,
    label,
    type,
    format: fieldFormat,
    description,
    required = false,
    register,
    errors,
    uiHints,
    enumValues,
    defaultValue,
  } = props;
  const { t } = useTranslation('omakase.editor');
  const [showPassword, setShowPassword] = useState(false);
  const fieldId = useId();
  const descriptionId = useId();
  const errorId = useId();

  const hasError = Boolean(errors[name]);
  const widget = uiHints?.widget || getDefaultWidget(type, fieldFormat, enumValues);
  const ariaAttributes = buildAriaAttributes({
    fieldId,
    descriptionId,
    errorId,
    description,
    hasError,
    required,
  });

  const commonProps: CommonFormProps = {
    ...register(name),
    ...ariaAttributes,
    placeholder: uiHints?.placeholder || t('fields.placeholder', { field: label.toLowerCase() }),
  };

  const requiredLabel = t('fields.required');
  const onTogglePassword = (): void => setShowPassword((prev) => !prev);

  const renderedField = renderFieldByWidget({
    widget,
    commonProps,
    hasError,
    enumValues,
    defaultValue,
    label,
    ariaAttributes,
    registerProps: register(name),
    fieldId,
    required,
    requiredLabel,
    showPassword,
    selectPlaceholder: t('fields.selectPlaceholder', { field: label.toLowerCase() }),
    showPasswordLabel: t('fields.showPassword'),
    hidePasswordLabel: t('fields.hidePassword'),
    onTogglePassword,
    type,
  });

  const errorMessage = hasError ? (
    <p id={errorId} className="text-destructive text-sm" role="alert">
      {errors[name]?.message || t('errors.invalidValue')}
    </p>
  ) : null;

  return widget === WIDGET_TYPES.CHECKBOX ? (
    <CheckboxLayout
      renderedField={renderedField}
      description={description}
      errorMessage={errorMessage}
    />
  ) : (
    <StandardFieldLayout
      fieldId={fieldId}
      label={label}
      required={required}
      requiredTitle={requiredLabel}
      description={description}
      renderedField={renderedField}
      errorMessage={errorMessage}
    />
  );
}
