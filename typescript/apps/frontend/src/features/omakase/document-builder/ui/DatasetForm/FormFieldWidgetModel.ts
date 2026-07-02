import type { UseFormRegisterReturn } from 'react-hook-form';

const WIDGET_TYPES = {
  SELECT: 'select',
  CHECKBOX: 'checkbox',
  TEXTAREA: 'textarea',
  EMAIL: 'email',
  PASSWORD: 'password',
  DATE: 'date',
  NUMBER: 'number',
  INPUT: 'input',
} as const;

type WidgetType = (typeof WIDGET_TYPES)[keyof typeof WIDGET_TYPES];

type CommonFormProps = UseFormRegisterReturn & {
  placeholder?: string | undefined;
  'aria-labelledby'?: string | undefined;
  'aria-describedby'?: string | undefined;
  'aria-invalid'?: boolean | undefined;
  'aria-errormessage'?: string | undefined;
  'aria-required'?: boolean | undefined;
};

interface AriaAttributes {
  'aria-labelledby': string;
  'aria-describedby'?: string | undefined;
  'aria-invalid': boolean;
  'aria-errormessage'?: string | undefined;
  'aria-required': boolean;
}

function getDefaultWidget(
  fieldType: string,
  fieldFormat?: string,
  enumVals?: readonly unknown[],
): WidgetType {
  if (enumVals !== undefined && enumVals.length > 0) {
    return WIDGET_TYPES.SELECT;
  }
  if (fieldType === 'boolean') {
    return WIDGET_TYPES.CHECKBOX;
  }
  if (fieldFormat === 'textarea') {
    return WIDGET_TYPES.TEXTAREA;
  }
  if (fieldFormat === 'email') {
    return WIDGET_TYPES.EMAIL;
  }
  if (fieldFormat === 'password') {
    return WIDGET_TYPES.PASSWORD;
  }
  if (fieldFormat === 'date') {
    return WIDGET_TYPES.DATE;
  }
  if (fieldType === 'number' || fieldType === 'integer') {
    return WIDGET_TYPES.NUMBER;
  }
  return WIDGET_TYPES.INPUT;
}

export type { AriaAttributes, CommonFormProps, WidgetType };
export { getDefaultWidget, WIDGET_TYPES };
