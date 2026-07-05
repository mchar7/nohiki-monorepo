import type { ContentSchema } from '@features/omakase/document-builder';
import type { OmakaseTemplateMetadata } from '../model/index.ts';

const DEFAULT_TEMPLATE = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ full_name }} - Document</title>
    <style>
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 20px;
            line-height: 1.6;
        }
        .header {
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }
        .contact-info {
            margin-top: 10px;
            font-size: 14px;
        }

        @page {
            size: 8.5in 11in;
            margin: 0;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>{{ full_name }}</h1>
        <h2>{{ professional_title }}</h2>
        <div class="contact-info">
            <p>Email: {{ contact.email }}</p>
            <p>Phone: {{ contact.phone }}</p>
            <p>Location: {{ contact.location }}</p>
            {% if contact.website %}
            <p>Website: {{ contact.website }}</p>
            {% endif %}
        </div>
    </div>

    <div class="content">
        <p>This is a sample template. Edit the HTML above to create your custom template.</p>
    </div>
</body>
</html>`;

const DEFAULT_METADATA: OmakaseTemplateMetadata = {
  id: '',
  name: 'New Template',
  description: 'A custom document template',
  version: '1.0.0',
  engine: 'jinja2',
  pageSize: { unit: 'in', width: 8.5, height: 11 },
};

const DEFAULT_CONTENT_SCHEMA: ContentSchema = {
  full_name: { type: 'string' },
  professional_title: { type: 'string' },
  contact: {
    type: 'object',
    properties: {
      email: { type: 'string' },
      phone: { type: 'string' },
      location: { type: 'string' },
      website: { type: 'string' },
    },
  },
};

/** Viewport width threshold below which single-pane layout is used (px) */
const SINGLE_PANE_THRESHOLD_PX: number = 1200;

export { DEFAULT_CONTENT_SCHEMA, DEFAULT_METADATA, DEFAULT_TEMPLATE, SINGLE_PANE_THRESHOLD_PX };
