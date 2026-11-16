// utils/copyId.ts
import { toast } from 'sonner';

/** An artifact's id onto the clipboard, and a word that it is there (BUG-075: Copy ID). */
export async function copyId(id: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(id);
    toast.success('ID copied', { description: id });
  } catch {
    toast.error('Could not copy the ID', { description: id });
  }
}
