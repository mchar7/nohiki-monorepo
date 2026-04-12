"""Services package for doc-template-service."""

from .render_storage import StoredRenderResult, store_rendered_document
from .template_service import (
    TemplateDuplicateError,
    TemplateNotFoundError,
    TemplateVersionError,
    create_template,
    delete_all_template_versions,
    delete_template,
    generate_etag,
    get_latest_template,
    get_template_by_id,
    get_template_by_name_version,
    get_template_model_by_id,
    list_template_versions,
    list_templates,
    template_exists,
    template_version_exists,
)

__all__ = [
    "StoredRenderResult",
    "TemplateDuplicateError",
    "TemplateNotFoundError",
    "TemplateVersionError",
    "create_template",
    "delete_all_template_versions",
    "delete_template",
    "generate_etag",
    "get_latest_template",
    "get_template_by_id",
    "get_template_by_name_version",
    "get_template_model_by_id",
    "list_template_versions",
    "list_templates",
    "store_rendered_document",
    "template_exists",
    "template_version_exists",
]
