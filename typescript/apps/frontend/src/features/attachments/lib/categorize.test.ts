import { afterEach, describe, expect } from 'vitest';
import { type DocumentCategory, inferCategory, loadCategory, saveCategory } from './categorize.ts';

describe('inferCategory - resume detection', () => {
  test('matches filenames containing "resume"', () => {
    expect(inferCategory('my_resume_v3.pdf')).toBe('resume');
    expect(inferCategory('Resume.pdf')).toBe('resume');
    expect(inferCategory('RESUME_2024.docx')).toBe('resume');
    expect(inferCategory('john-resume-final.pdf')).toBe('resume');
  });

  test('matches filenames containing "cv"', () => {
    expect(inferCategory('cv.pdf')).toBe('resume');
    expect(inferCategory('CV_John_Doe.pdf')).toBe('resume');
    expect(inferCategory('my-cv-2024.docx')).toBe('resume');
  });

  test('matches filenames containing "curriculum"', () => {
    expect(inferCategory('curriculum_vitae.pdf')).toBe('resume');
    expect(inferCategory('Curriculum-Vitae-2024.docx')).toBe('resume');
  });
});

describe('inferCategory - cover letter detection', () => {
  test('matches filenames containing "cover"', () => {
    expect(inferCategory('cover_letter.pdf')).toBe('cover_letter');
    expect(inferCategory('Cover Letter - Google.docx')).toBe('cover_letter');
    expect(inferCategory('coverletter_v2.pdf')).toBe('cover_letter');
    expect(inferCategory('my-cover-letter.pdf')).toBe('cover_letter');
  });

  test('matches filenames containing "motivation"', () => {
    expect(inferCategory('motivation_letter.pdf')).toBe('cover_letter');
    expect(inferCategory('Motivation-Letter.docx')).toBe('cover_letter');
  });
});

describe('inferCategory - portfolio and other', () => {
  test('matches filenames containing "portfolio"', () => {
    expect(inferCategory('portfolio.pdf')).toBe('portfolio');
    expect(inferCategory('My_Portfolio_2024.pdf')).toBe('portfolio');
    expect(inferCategory('design-portfolio.pdf')).toBe('portfolio');
  });

  test('matches filenames containing "folio"', () => {
    expect(inferCategory('folio.pdf')).toBe('portfolio');
  });

  test('matches filenames containing "work_samples"', () => {
    expect(inferCategory('work_samples.pdf')).toBe('portfolio');
    expect(inferCategory('work-samples-2024.pdf')).toBe('portfolio');
  });

  test('returns "other" for unrecognized filenames', () => {
    expect(inferCategory('document.pdf')).toBe('other');
    expect(inferCategory('notes.txt')).toBe('other');
    expect(inferCategory('report_q4.docx')).toBe('other');
    expect(inferCategory('random_file.pdf')).toBe('other');
  });

  test('handles filenames without extensions', () => {
    expect(inferCategory('resume')).toBe('resume');
    expect(inferCategory('cover_letter')).toBe('cover_letter');
    expect(inferCategory('unknown')).toBe('other');
  });

  test('is case-insensitive', () => {
    expect(inferCategory('MY_RESUME.PDF')).toBe('resume');
    expect(inferCategory('Cover_Letter.DOCX')).toBe('cover_letter');
    expect(inferCategory('PORTFOLIO.pdf')).toBe('portfolio');
  });

  test('handles special characters in filenames', () => {
    expect(inferCategory('resume (1).pdf')).toBe('resume');
    expect(inferCategory('cover.letter.final.pdf')).toBe('cover_letter');
    expect(inferCategory('my resume - v2.pdf')).toBe('resume');
  });
});

describe('saveCategory / loadCategory', () => {
  afterEach(() => {
    localStorage.clear();
  });

  test('persists and retrieves a category', () => {
    saveCategory('upload-123', 'resume');
    expect(loadCategory('upload-123')).toBe('resume');
  });

  test('returns null for unknown upload IDs', () => {
    expect(loadCategory('nonexistent')).toBeNull();
  });

  test('returns null for invalid stored values', () => {
    localStorage.setItem('attachment-category:bad', 'invalid_value');
    expect(loadCategory('bad')).toBeNull();
  });

  test('handles all valid categories', () => {
    const categories: DocumentCategory[] = ['resume', 'cover_letter', 'portfolio', 'other'];
    for (const category of categories) {
      saveCategory(`id-${category}`, category);
      expect(loadCategory(`id-${category}`)).toBe(category);
    }
  });
});
