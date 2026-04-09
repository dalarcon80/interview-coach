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
  Building2, 
  MapPin, 
  Briefcase, 
  DollarSign, 
  Link2, 
  Plus, 
  X, 
  Save, 
  Loader2,
  Users,
  Target
} from 'lucide-react';

export interface CompanyInfo {
  id?: string;
  companyName: string;
  industry?: string;
  companySize?: string;
  companyDescription?: string;
  companyValues?: string[];
  companyCulture?: string;
  positionTitle: string;
  positionLevel?: string;
  positionDepartment?: string;
  positionDescription?: string;
  positionRequirements?: string[];
  salaryRange?: string;
  location?: string;
  workMode?: string;
  jobPostingUrl?: string;
  notes?: string;
}

interface CompanyInfoFormProps {
  company?: CompanyInfo | null;
  onSave: (company: CompanyInfo) => Promise<void>;
  isLoading?: boolean;
}

const COMPANY_SIZES = [
  { value: 'startup', label: 'Startup (< 50 empleados)' },
  { value: 'small', label: 'Pequeña (50-200 empleados)' },
  { value: 'medium', label: 'Mediana (200-1000 empleados)' },
  { value: 'large', label: 'Grande (1000-5000 empleados)' },
  { value: 'enterprise', label: 'Enterprise (5000+ empleados)' },
];

const POSITION_LEVELS = [
  { value: 'junior', label: 'Junior' },
  { value: 'mid', label: 'Mid-Level' },
  { value: 'senior', label: 'Senior' },
  { value: 'lead', label: 'Tech Lead' },
  { value: 'manager', label: 'Manager' },
  { value: 'director', label: 'Director' },
  { value: 'c-level', label: 'C-Level' },
];

const WORK_MODES = [
  { value: 'remote', label: 'Remoto' },
  { value: 'hybrid', label: 'Híbrido' },
  { value: 'onsite', label: 'Presencial' },
];

export function CompanyInfoForm({ company, onSave, isLoading }: CompanyInfoFormProps) {
  const [formData, setFormData] = useState<CompanyInfo>({
    companyName: company?.companyName || '',
    industry: company?.industry || '',
    companySize: company?.companySize || '',
    companyDescription: company?.companyDescription || '',
    companyValues: company?.companyValues || [],
    companyCulture: company?.companyCulture || '',
    positionTitle: company?.positionTitle || '',
    positionLevel: company?.positionLevel || '',
    positionDepartment: company?.positionDepartment || '',
    positionDescription: company?.positionDescription || '',
    positionRequirements: company?.positionRequirements || [],
    salaryRange: company?.salaryRange || '',
    location: company?.location || '',
    workMode: company?.workMode || '',
    jobPostingUrl: company?.jobPostingUrl || '',
    notes: company?.notes || '',
  });

  const [newValue, setNewValue] = useState('');
  const [newRequirement, setNewRequirement] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!formData.companyName.trim() || !formData.positionTitle.trim()) return;
    setSaving(true);
    try {
      await onSave(formData);
    } finally {
      setSaving(false);
    }
  };

  const addValue = () => {
    if (newValue.trim()) {
      setFormData(prev => ({
        ...prev,
        companyValues: [...(prev.companyValues || []), newValue.trim()]
      }));
      setNewValue('');
    }
  };

  const removeValue = (index: number) => {
    setFormData(prev => ({
      ...prev,
      companyValues: prev.companyValues?.filter((_, i) => i !== index)
    }));
  };

  const addRequirement = () => {
    if (newRequirement.trim()) {
      setFormData(prev => ({
        ...prev,
        positionRequirements: [...(prev.positionRequirements || []), newRequirement.trim()]
      }));
      setNewRequirement('');
    }
  };

  const removeRequirement = (index: number) => {
    setFormData(prev => ({
      ...prev,
      positionRequirements: prev.positionRequirements?.filter((_, i) => i !== index)
    }));
  };

  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Building2 className="h-5 w-5 text-primary" />
          <CardTitle className="text-lg">Empresa y Cargo</CardTitle>
        </div>
        <CardDescription>
          Información de la empresa y el puesto al que aplicas
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 max-h-[600px] overflow-y-auto">
        {/* Company Info */}
        <div className="space-y-3">
          <h4 className="text-sm font-medium text-muted-foreground flex items-center gap-1">
            <Building2 className="h-4 w-4" /> Empresa
          </h4>
          
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="companyName">Nombre de la empresa *</Label>
              <Input
                id="companyName"
                value={formData.companyName}
                onChange={(e) => setFormData(prev => ({ ...prev, companyName: e.target.value }))}
                placeholder="Google, Amazon, etc."
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="industry">Industria</Label>
              <Input
                id="industry"
                value={formData.industry || ''}
                onChange={(e) => setFormData(prev => ({ ...prev, industry: e.target.value }))}
                placeholder="Tecnología, Finanzas, etc."
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>Tamaño</Label>
              <Select
                value={formData.companySize || ''}
                onValueChange={(value) => setFormData(prev => ({ ...prev, companySize: value }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Seleccionar..." />
                </SelectTrigger>
                <SelectContent>
                  {COMPANY_SIZES.map(size => (
                    <SelectItem key={size.value} value={size.value}>{size.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Modalidad</Label>
              <Select
                value={formData.workMode || ''}
                onValueChange={(value) => setFormData(prev => ({ ...prev, workMode: value }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Seleccionar..." />
                </SelectTrigger>
                <SelectContent>
                  {WORK_MODES.map(mode => (
                    <SelectItem key={mode.value} value={mode.value}>{mode.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label>Descripción de la empresa</Label>
            <Textarea
              value={formData.companyDescription || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, companyDescription: e.target.value }))}
              placeholder="Breve descripción de la empresa..."
              rows={2}
            />
          </div>

          {/* Company Values */}
          <div className="space-y-2">
            <Label className="flex items-center gap-1">
              <Target className="h-4 w-4" /> Valores de la empresa
            </Label>
            <div className="flex gap-2">
              <Input
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
                placeholder="Agregar valor..."
                onKeyPress={(e) => e.key === 'Enter' && addValue()}
              />
              <Button type="button" size="sm" onClick={addValue}>
                <Plus className="h-4 w-4" />
              </Button>
            </div>
            <div className="flex flex-wrap gap-1 mt-2">
              {formData.companyValues?.map((value, index) => (
                <Badge key={index} variant="secondary" className="gap-1">
                  {value}
                  <X className="h-3 w-3 cursor-pointer" onClick={() => removeValue(index)} />
                </Badge>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label>Cultura de la empresa</Label>
            <Textarea
              value={formData.companyCulture || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, companyCulture: e.target.value }))}
              placeholder="Describe la cultura de trabajo..."
              rows={2}
            />
          </div>
        </div>

        {/* Divider */}
        <div className="border-t pt-3">
          <h4 className="text-sm font-medium text-muted-foreground flex items-center gap-1 mb-3">
            <Briefcase className="h-4 w-4" /> Puesto
          </h4>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="positionTitle">Título del puesto *</Label>
              <Input
                id="positionTitle"
                value={formData.positionTitle}
                onChange={(e) => setFormData(prev => ({ ...prev, positionTitle: e.target.value }))}
                placeholder="Software Engineer"
              />
            </div>
            <div className="space-y-2">
              <Label>Nivel del puesto</Label>
              <Select
                value={formData.positionLevel || ''}
                onValueChange={(value) => setFormData(prev => ({ ...prev, positionLevel: value }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Seleccionar..." />
                </SelectTrigger>
                <SelectContent>
                  {POSITION_LEVELS.map(level => (
                    <SelectItem key={level.value} value={level.value}>{level.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mt-3">
            <div className="space-y-2">
              <Label>Departamento</Label>
              <Input
                value={formData.positionDepartment || ''}
                onChange={(e) => setFormData(prev => ({ ...prev, positionDepartment: e.target.value }))}
                placeholder="Engineering, Product, etc."
              />
            </div>
            <div className="space-y-2">
              <Label className="flex items-center gap-1">
                <MapPin className="h-4 w-4" /> Ubicación
              </Label>
              <Input
                value={formData.location || ''}
                onChange={(e) => setFormData(prev => ({ ...prev, location: e.target.value }))}
                placeholder="Ciudad, País"
              />
            </div>
          </div>

          <div className="space-y-2 mt-3">
            <Label>Descripción del puesto</Label>
            <Textarea
              value={formData.positionDescription || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, positionDescription: e.target.value }))}
              placeholder="Describe las responsabilidades del puesto..."
              rows={3}
            />
          </div>

          {/* Requirements */}
          <div className="space-y-2 mt-3">
            <Label>Requisitos del puesto</Label>
            <div className="flex gap-2">
              <Input
                value={newRequirement}
                onChange={(e) => setNewRequirement(e.target.value)}
                placeholder="Agregar requisito..."
                onKeyPress={(e) => e.key === 'Enter' && addRequirement()}
              />
              <Button type="button" size="sm" onClick={addRequirement}>
                <Plus className="h-4 w-4" />
              </Button>
            </div>
            <div className="space-y-1 mt-2">
              {formData.positionRequirements?.map((req, index) => (
                <div key={index} className="flex items-center justify-between bg-muted p-2 rounded text-sm">
                  <span>{req}</span>
                  <X className="h-4 w-4 cursor-pointer text-muted-foreground hover:text-destructive" onClick={() => removeRequirement(index)} />
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mt-3">
            <div className="space-y-2">
              <Label className="flex items-center gap-1">
                <DollarSign className="h-4 w-4" /> Rango salarial
              </Label>
              <Input
                value={formData.salaryRange || ''}
                onChange={(e) => setFormData(prev => ({ ...prev, salaryRange: e.target.value }))}
                placeholder="$80k - $120k"
              />
            </div>
            <div className="space-y-2">
              <Label className="flex items-center gap-1">
                <Link2 className="h-4 w-4" /> URL de la oferta
              </Label>
              <Input
                value={formData.jobPostingUrl || ''}
                onChange={(e) => setFormData(prev => ({ ...prev, jobPostingUrl: e.target.value }))}
                placeholder="https://..."
              />
            </div>
          </div>

          <div className="space-y-2 mt-3">
            <Label>Notas adicionales</Label>
            <Textarea
              value={formData.notes || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, notes: e.target.value }))}
              placeholder="Cualquier información adicional..."
              rows={2}
            />
          </div>
        </div>

        {/* Save Button */}
        <Button 
          className="w-full" 
          onClick={handleSave}
          disabled={!formData.companyName.trim() || !formData.positionTitle.trim() || saving || isLoading}
        >
          {saving || isLoading ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Guardando...
            </>
          ) : (
            <>
              <Save className="h-4 w-4 mr-2" />
              Guardar Información
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}
