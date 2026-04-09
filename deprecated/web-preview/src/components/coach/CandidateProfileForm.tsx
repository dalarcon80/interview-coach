'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select';
import { 
  User, 
  Briefcase, 
  Building2, 
  GraduationCap, 
  Award, 
  Globe, 
  Link2, 
  Plus, 
  X, 
  Save, 
  Loader2 
} from 'lucide-react';

export interface CandidateProfile {
  id?: string;
  name: string;
  email?: string;
  phone?: string;
  currentRole?: string;
  currentCompany?: string;
  yearsExperience?: number;
  skills?: string[];
  achievements?: string[];
  education?: { degree: string; institution: string; year: string }[];
  languages?: string[];
  certifications?: string[];
  linkedinUrl?: string;
  portfolioUrl?: string;
  summary?: string;
  rawResume?: string;
}

interface CandidateProfileFormProps {
  profile?: CandidateProfile | null;
  onSave: (profile: CandidateProfile) => Promise<void>;
  isLoading?: boolean;
}

export function CandidateProfileForm({ profile, onSave, isLoading }: CandidateProfileFormProps) {
  const [formData, setFormData] = useState<CandidateProfile>({
    name: profile?.name || '',
    email: profile?.email || '',
    phone: profile?.phone || '',
    currentRole: profile?.currentRole || '',
    currentCompany: profile?.currentCompany || '',
    yearsExperience: profile?.yearsExperience || 0,
    skills: profile?.skills || [],
    achievements: profile?.achievements || [],
    education: profile?.education || [],
    languages: profile?.languages || [],
    certifications: profile?.certifications || [],
    linkedinUrl: profile?.linkedinUrl || '',
    portfolioUrl: profile?.portfolioUrl || '',
    summary: profile?.summary || '',
    rawResume: profile?.rawResume || '',
  });

  const [newSkill, setNewSkill] = useState('');
  const [newAchievement, setNewAchievement] = useState('');
  const [newLanguage, setNewLanguage] = useState('');
  const [newCertification, setNewCertification] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!formData.name.trim()) return;
    setSaving(true);
    try {
      await onSave(formData);
    } finally {
      setSaving(false);
    }
  };

  const addSkill = () => {
    if (newSkill.trim()) {
      setFormData(prev => ({
        ...prev,
        skills: [...(prev.skills || []), newSkill.trim()]
      }));
      setNewSkill('');
    }
  };

  const removeSkill = (index: number) => {
    setFormData(prev => ({
      ...prev,
      skills: prev.skills?.filter((_, i) => i !== index)
    }));
  };

  const addAchievement = () => {
    if (newAchievement.trim()) {
      setFormData(prev => ({
        ...prev,
        achievements: [...(prev.achievements || []), newAchievement.trim()]
      }));
      setNewAchievement('');
    }
  };

  const removeAchievement = (index: number) => {
    setFormData(prev => ({
      ...prev,
      achievements: prev.achievements?.filter((_, i) => i !== index)
    }));
  };

  const addLanguage = () => {
    if (newLanguage.trim()) {
      setFormData(prev => ({
        ...prev,
        languages: [...(prev.languages || []), newLanguage.trim()]
      }));
      setNewLanguage('');
    }
  };

  const removeLanguage = (index: number) => {
    setFormData(prev => ({
      ...prev,
      languages: prev.languages?.filter((_, i) => i !== index)
    }));
  };

  const addCertification = () => {
    if (newCertification.trim()) {
      setFormData(prev => ({
        ...prev,
        certifications: [...(prev.certifications || []), newCertification.trim()]
      }));
      setNewCertification('');
    }
  };

  const removeCertification = (index: number) => {
    setFormData(prev => ({
      ...prev,
      certifications: prev.certifications?.filter((_, i) => i !== index)
    }));
  };

  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <User className="h-5 w-5 text-primary" />
          <CardTitle className="text-lg">Perfil del Candidato</CardTitle>
        </div>
        <CardDescription>
          Información personal y profesional para personalizar las respuestas
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 max-h-[600px] overflow-y-auto">
        {/* Personal Info */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="name">Nombre completo *</Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
              placeholder="Juan Pérez"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={formData.email || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, email: e.target.value }))}
              placeholder="juan@email.com"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="phone">Teléfono</Label>
            <Input
              id="phone"
              value={formData.phone || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, phone: e.target.value }))}
              placeholder="+1 234 567 890"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="yearsExperience">Años de experiencia</Label>
            <Input
              id="yearsExperience"
              type="number"
              min="0"
              max="50"
              value={formData.yearsExperience || 0}
              onChange={(e) => setFormData(prev => ({ ...prev, yearsExperience: parseInt(e.target.value) || 0 }))}
            />
          </div>
        </div>

        {/* Current Position */}
        <div className="space-y-2">
          <Label className="flex items-center gap-1">
            <Briefcase className="h-4 w-4" /> Cargo actual
          </Label>
          <Input
            value={formData.currentRole || ''}
            onChange={(e) => setFormData(prev => ({ ...prev, currentRole: e.target.value }))}
            placeholder="Senior Software Engineer"
          />
        </div>

        <div className="space-y-2">
          <Label className="flex items-center gap-1">
            <Building2 className="h-4 w-4" /> Empresa actual
          </Label>
          <Input
            value={formData.currentCompany || ''}
            onChange={(e) => setFormData(prev => ({ ...prev, currentCompany: e.target.value }))}
            placeholder="Tech Corp"
          />
        </div>

        {/* Skills */}
        <div className="space-y-2">
          <Label className="flex items-center gap-1">
            <Award className="h-4 w-4" /> Habilidades
          </Label>
          <div className="flex gap-2">
            <Input
              value={newSkill}
              onChange={(e) => setNewSkill(e.target.value)}
              placeholder="Agregar habilidad..."
              onKeyPress={(e) => e.key === 'Enter' && addSkill()}
            />
            <Button type="button" size="sm" onClick={addSkill}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex flex-wrap gap-1 mt-2">
            {formData.skills?.map((skill, index) => (
              <Badge key={index} variant="secondary" className="gap-1">
                {skill}
                <X className="h-3 w-3 cursor-pointer" onClick={() => removeSkill(index)} />
              </Badge>
            ))}
          </div>
        </div>

        {/* Achievements */}
        <div className="space-y-2">
          <Label className="flex items-center gap-1">
            <Award className="h-4 w-4" /> Logros destacados
          </Label>
          <div className="flex gap-2">
            <Input
              value={newAchievement}
              onChange={(e) => setNewAchievement(e.target.value)}
              placeholder="Agregar logro..."
              onKeyPress={(e) => e.key === 'Enter' && addAchievement()}
            />
            <Button type="button" size="sm" onClick={addAchievement}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <div className="space-y-1 mt-2">
            {formData.achievements?.map((achievement, index) => (
              <div key={index} className="flex items-center justify-between bg-muted p-2 rounded text-sm">
                <span>{achievement}</span>
                <X className="h-4 w-4 cursor-pointer text-muted-foreground hover:text-destructive" onClick={() => removeAchievement(index)} />
              </div>
            ))}
          </div>
        </div>

        {/* Languages */}
        <div className="space-y-2">
          <Label className="flex items-center gap-1">
            <Globe className="h-4 w-4" /> Idiomas
          </Label>
          <div className="flex gap-2">
            <Input
              value={newLanguage}
              onChange={(e) => setNewLanguage(e.target.value)}
              placeholder="Agregar idioma..."
              onKeyPress={(e) => e.key === 'Enter' && addLanguage()}
            />
            <Button type="button" size="sm" onClick={addLanguage}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex flex-wrap gap-1 mt-2">
            {formData.languages?.map((language, index) => (
              <Badge key={index} variant="outline" className="gap-1">
                {language}
                <X className="h-3 w-3 cursor-pointer" onClick={() => removeLanguage(index)} />
              </Badge>
            ))}
          </div>
        </div>

        {/* Certifications */}
        <div className="space-y-2">
          <Label className="flex items-center gap-1">
            <GraduationCap className="h-4 w-4" /> Certificaciones
          </Label>
          <div className="flex gap-2">
            <Input
              value={newCertification}
              onChange={(e) => setNewCertification(e.target.value)}
              placeholder="Agregar certificación..."
              onKeyPress={(e) => e.key === 'Enter' && addCertification()}
            />
            <Button type="button" size="sm" onClick={addCertification}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex flex-wrap gap-1 mt-2">
            {formData.certifications?.map((cert, index) => (
              <Badge key={index} variant="secondary" className="gap-1">
                {cert}
                <X className="h-3 w-3 cursor-pointer" onClick={() => removeCertification(index)} />
              </Badge>
            ))}
          </div>
        </div>

        {/* Links */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label className="flex items-center gap-1">
              <Link2 className="h-4 w-4" /> LinkedIn
            </Label>
            <Input
              value={formData.linkedinUrl || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, linkedinUrl: e.target.value }))}
              placeholder="https://linkedin.com/in/..."
            />
          </div>
          <div className="space-y-2">
            <Label className="flex items-center gap-1">
              <Link2 className="h-4 w-4" /> Portfolio
            </Label>
            <Input
              value={formData.portfolioUrl || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, portfolioUrl: e.target.value }))}
              placeholder="https://..."
            />
          </div>
        </div>

        {/* Summary */}
        <div className="space-y-2">
          <Label>Resumen profesional</Label>
          <Textarea
            value={formData.summary || ''}
            onChange={(e) => setFormData(prev => ({ ...prev, summary: e.target.value }))}
            placeholder="Breve resumen de tu perfil profesional..."
            rows={3}
          />
        </div>

        {/* Save Button */}
        <Button 
          className="w-full" 
          onClick={handleSave}
          disabled={!formData.name.trim() || saving || isLoading}
        >
          {saving || isLoading ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Guardando...
            </>
          ) : (
            <>
              <Save className="h-4 w-4 mr-2" />
              Guardar Perfil
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}
