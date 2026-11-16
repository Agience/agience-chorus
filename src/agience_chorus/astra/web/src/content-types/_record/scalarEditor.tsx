export type FieldDescriptor = {
  path: string;
  label?: string;
  editable?: boolean;
  editor?: 'text' | 'number' | 'url' | 'textarea' | 'boolean' | 'select';
  /** With `editor: "select"`: the values it may take, in order (a type's enum). */
  options?: string[];
};

type ScalarEditorProps = {
  id: string;
  descriptor: FieldDescriptor;
  value: unknown;
  onChange: (value: unknown) => void;
};

function normalizeScalarValue(descriptor: FieldDescriptor, raw: string, currentValue: unknown): unknown {
  const editor = descriptor.editor ?? 'text';
  if (editor === 'number') {
    if (raw.trim() === '') return '';
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : currentValue;
  }
  if (editor === 'boolean') {
    return raw === 'true';
  }
  return raw;
}

/** The one scalar editor every record field uses. */
export function renderScalarEditor({ id, descriptor, value, onChange }: ScalarEditorProps) {
  const editor = descriptor.editor ?? 'text';
  const normalizedValue = value === null || value === undefined ? '' : String(value);

  if (editor === 'textarea') {
    return (
      <textarea
        id={id}
        value={normalizedValue}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-[88px] rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      />
    );
  }

  // A field limited to its type's values (G6: a Backlog item's state). A stored value the list does
  // not hold is shown as it is, and choosing a listed one replaces it; nothing else can be typed.
  if (editor === 'select') {
    const options = descriptor.options ?? [];
    const listed = options.includes(normalizedValue);
    return (
      <select
        id={id}
        value={normalizedValue}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      >
        {!listed && <option value={normalizedValue}>{normalizedValue || '—'}</option>}
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    );
  }

  if (editor === 'boolean') {
    return (
      <label className="flex items-center gap-2 text-sm text-gray-800">
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        />
        Enabled
      </label>
    );
  }

  return (
    <input
      id={id}
      type={editor}
      value={normalizedValue}
      onChange={(event) => onChange(normalizeScalarValue(descriptor, event.target.value, value))}
      className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
    />
  );
}
